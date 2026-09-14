/* 공용 포맷·계산 유틸 - overview/positions/activity/performance/system 탭이
   전부 이걸 쓴다. chart.js(구 "차트" 탭, 이번 개편으로 대체됨)에 있던 로직을
   그대로 옮긴 것 - 새로 설계하지 않았다. window.PT 네임스페이스 하나로 모아
   탭마다 <script> 로드 순서(lib.js가 먼저)만 지키면 된다. */
window.PT = (function () {
  function formatAccount(value) {
    if (value === null || value === undefined) return '<span class="warn">조회 실패</span>';
    return value.toLocaleString("ko-KR", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }

  function formatPrice(price) {
    if (price === null || price === undefined) return "-";
    return price.toLocaleString("ko-KR", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }

  function formatPnl(pnl) {
    if (pnl === null || pnl === undefined) return "-";
    const sign = pnl >= 0 ? "+" : "";
    return sign + pnl.toLocaleString("ko-KR", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }

  function formatPnlPct(pct) {
    if (pct === null || pct === undefined) return "-";
    const sign = pct >= 0 ? "+" : "";
    return sign + pct.toFixed(2) + "%";
  }

  function getPnlClass(value) {
    if (value === null || value === undefined) return "";
    return value >= 0 ? "up" : "down";
  }

  function getStatusBadgeClass(status) {
    if (status === "PENDING_ENTRY" || status === "ENTRY_SUBMITTED") return "status-pending";
    if (status === "EXIT_SUBMITTED") return "status-submitted";
    if (status === "OPEN") return "status-open";
    return "";
  }

  // SVG는 실제 DOM이라 style="stroke:var(...)"가 테마 전환에 그냥 반응한다 -
  // 캔버스와 달리 cssVar() 조회나 themechange 리스너가 따로 필요 없다.
  function sparklineSvg(history) {
    if (!history || history.length < 2) return '<span class="dim">-</span>';
    const closes = history.slice(-40).map((h) => h.close);
    const min = Math.min(...closes);
    const max = Math.max(...closes);
    const range = max - min || 1;
    const w = 80, h = 24, pad = 2;
    const pts = closes.map((c, i) => {
      const x = (i / (closes.length - 1)) * (w - pad * 2) + pad;
      const y = h - pad - ((c - min) / range) * (h - pad * 2);
      return x.toFixed(1) + "," + y.toFixed(1);
    }).join(" ");
    const color = closes[closes.length - 1] >= closes[0] ? "var(--up)" : "var(--down)";
    return '<svg width="' + w + '" height="' + h + '" viewBox="0 0 ' + w + " " + h + '">' +
      '<polyline points="' + pts + '" fill="none" style="stroke:' + color +
      ';stroke-width:1.5;stroke-linejoin:round;stroke-linecap:round" /></svg>';
  }

  // 전략 한 덩어리의 원가·평가·손익. 원가는 평단가가 있는 포지션만 센다
  // (PENDING_ENTRY는 아직 산 게 아니다 - 0으로 세면 손익률 분모가 부풀어
  // 수익률이 작아 보인다, 교훈57).
  function strategyTotals(positions) {
    let cost = 0, value = 0, pnl = 0, priced = 0;
    (positions || []).forEach((p) => {
      const qty = p.quantity || 0;
      const lastClose = p.history && p.history.length ? p.history[p.history.length - 1].close : null;
      const mark = p.currentPrice ?? lastClose;
      if (mark) value += mark * qty;
      if (p.avgEntryPrice) { cost += p.avgEntryPrice * qty; priced += 1; }
      if (typeof p.unrealizedPnlKrw === "number") pnl += p.unrealizedPnlKrw;
    });
    return { cost, value, pnl, pnlPct: cost ? (pnl / cost) * 100 : null, priced };
  }

  // Beta·연환산 변동성 - 종목 종가와 벤치마크를 날짜로 맞춘 뒤 일별
  // 수익률로 계산한다. 겹치는 거래일이 20일 미만이면 노이즈만 큰 숫자를
  // 보여주는 셈이라 아예 null로 유보한다("정직한 점수" 원칙).
  function computeRiskMetrics(history, benchHist) {
    if (!history || !benchHist) return null;
    const benchMap = new Map(benchHist.map((h) => [h.date, h.value]));
    const aligned = history.filter((h) => benchMap.has(h.date));
    if (aligned.length < 21) return null;

    const stockRet = [], benchRet = [];
    for (let i = 1; i < aligned.length; i++) {
      const prevB = benchMap.get(aligned[i - 1].date);
      const curB = benchMap.get(aligned[i].date);
      stockRet.push(aligned[i].close / aligned[i - 1].close - 1);
      benchRet.push(curB / prevB - 1);
    }
    const n = stockRet.length;
    const mean = (arr) => arr.reduce((a, b) => a + b, 0) / arr.length;
    const meanS = mean(stockRet), meanB = mean(benchRet);
    let cov = 0, varB = 0, varS = 0;
    for (let i = 0; i < n; i++) {
      const ds = stockRet[i] - meanS, db = benchRet[i] - meanB;
      cov += ds * db; varB += db * db; varS += ds * ds;
    }
    cov /= n; varB /= n; varS /= n;
    return { beta: varB > 0 ? cov / varB : null, volAnnualPct: Math.sqrt(varS) * Math.sqrt(252) * 100, n };
  }

  // new Date().toISOString()는 UTC라 KST 자정~오전9시엔 날짜가 하루 밀린다.
  function kstNow() { return new Date(Date.now() + 9 * 3600 * 1000); }

  // 장중 여부 - 순수 시각 계산(공휴일은 모른다, 절대 규칙 3: 시각은 KST).
  // 사실이 아닌 걸 지어내지 않는 선에서 낼 수 있는 최대치 - "공휴일 미반영"을
  // 라벨에 명시해 과장하지 않는다.
  function marketSession() {
    const now = kstNow();
    const day = now.getUTCDay(); // kstNow는 이미 +9시간 된 Date라 getUTC*가 KST 시각
    const hm = now.getUTCHours() * 60 + now.getUTCMinutes();
    if (day === 0 || day === 6) return { open: false, label: "휴장(주말)" };
    if (hm >= 9 * 60 && hm < 15 * 60 + 30) return { open: true, label: "장중" };
    return { open: false, label: "장마감" };
  }

  async function fetchJson(path) {
    const res = await fetch(path + "?t=" + Date.now());
    if (!res.ok) throw new Error("HTTP " + res.status + " (" + path + ")");
    return res.json();
  }

  async function tryFetchJson(path) {
    try { return await fetchJson(path); } catch (e) { return null; }
  }

  return {
    formatAccount, formatPrice, formatPnl, formatPnlPct, getPnlClass, getStatusBadgeClass,
    sparklineSvg, strategyTotals, computeRiskMetrics, kstNow, marketSession,
    fetchJson, tryFetchJson,
  };
})();
