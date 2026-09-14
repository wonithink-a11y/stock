/* 업비트·빗썸 실계좌 서브탭에 얹는 실시간 시세 패널 - 주요 10종목 현재가·
   24시간 등락률·프리미엄, 코인을 클릭하면 그 행 바로 아래에 캔들 차트가
   인라인으로 펼쳐진다(타임프레임 1분/5분/30분/1시간/일봉 선택 + 이동평균선
   5/20/60/120 토글, TradingView의 오픈소스 lightweight-charts로 그린다 -
   캔들·오버레이 렌더링을 손으로 새로 짜지 않는다, 필요할 때만 CDN에서
   불러온다). RSI·MACD·이격도·매수매도비율은 이번 범위에 없다(2026-09-15
   사용자 확인 - 핵심만 먼저).

   거래소 공개 API(Upbit/Bithumb/Binance)는 Access-Control-Allow-Origin: *
   를 낸다(2026-09-14 실측) - 백엔드 없이 브라우저에서 바로 조회한다. 조회
   전용 원칙과도 맞다(주문 API는 안 쓴다).

   프리미엄 = 국내가 / (바이낸스 USDT가 × USDT/KRW) - 1. USDT/KRW는 업비트
   KRW-USDT 시장가를 업비트·빗썸 공통 기준으로 쓴다 - 거래소마다 따로 재면
   각자의 USDT 마켓 유동성 차이가 프리미엄값에 섞여 들어간다.

   30초 자동 갱신은 가격 셀만 제자리에서 바꾼다(테이블 구조를 다시 안
   그린다) - 열려있는 인라인 차트를 갱신 때마다 부수고 다시 만들면 pan/zoom
   위치가 매번 날아간다. 차트 자체(캔들 데이터)는 타임프레임을 바꾸거나
   다시 열 때만 새로 받는다. */
window.CryptoTicker = (function () {
  const REFRESH_MS = 30000;
  let refreshTimer = null;

  const COINS = [
    { code: "BTC", name: "비트코인" },
    { code: "ETH", name: "이더리움" },
    { code: "XRP", name: "리플" },
    { code: "SOL", name: "솔라나" },
    { code: "DOGE", name: "도지코인" },
    { code: "ADA", name: "에이다" },
    { code: "TRX", name: "트론" },
    { code: "DOT", name: "폴카닷" },
    { code: "AVAX", name: "아발란체" },
    { code: "LINK", name: "체인링크" },
  ];

  // 업비트 분봉 unit·빗썸 candlestick interval이 서로 다른 값을 쓴다 - 둘 다
  // 지원하는 교집합만 고른다(업비트는 15분이 있지만 빗썸엔 없다, 대신 30분은
  // 둘 다 있다).
  const TIMEFRAMES = [
    { id: "1m", label: "1분", upbitUnit: 1, bithumbInterval: "1m" },
    { id: "5m", label: "5분", upbitUnit: 5, bithumbInterval: "5m" },
    { id: "30m", label: "30분", upbitUnit: 30, bithumbInterval: "30m" },
    { id: "1h", label: "1시간", upbitUnit: 60, bithumbInterval: "1h" },
    { id: "1d", label: "일봉", upbitUnit: null, bithumbInterval: "24h" },
  ];
  const MA_PERIODS = [5, 20, 60, 120];
  const MA_COLORS = { 5: "#f5a623", 20: "#4f8ef7", 60: "#b45cff", 120: "#2ecc71" };

  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  async function fetchUpbitTickers(codes) {
    const res = await fetch("https://api.upbit.com/v1/ticker?markets=" + codes.map((c) => "KRW-" + c).join(","));
    if (!res.ok) throw new Error("업비트 시세 HTTP " + res.status);
    const byCode = {};
    (await res.json()).forEach((r) => {
      byCode[r.market.replace("KRW-", "")] = { price: r.trade_price, changePct: r.signed_change_rate * 100 };
    });
    return byCode;
  }

  async function fetchBithumbTickers(codes) {
    const res = await fetch("https://api.bithumb.com/public/ticker/ALL_KRW");
    if (!res.ok) throw new Error("빗썸 시세 HTTP " + res.status);
    const j = await res.json();
    if (j.status !== "0000") throw new Error("빗썸 시세 응답 오류 (status " + j.status + ")");
    const byCode = {};
    codes.forEach((c) => {
      const d = j.data[c];
      if (!d) return;
      byCode[c] = { price: Number(d.closing_price), changePct: Number(d.fluctate_rate_24H) };
    });
    return byCode;
  }

  async function fetchBinanceUsdt(codes) {
    const symbols = encodeURIComponent(JSON.stringify(codes.map((c) => c + "USDT")));
    const res = await fetch("https://api.binance.com/api/v3/ticker/price?symbols=" + symbols);
    if (!res.ok) throw new Error("바이낸스 시세 HTTP " + res.status);
    const byCode = {};
    (await res.json()).forEach((r) => { byCode[r.symbol.replace("USDT", "")] = Number(r.price); });
    return byCode;
  }

  async function fetchUsdtKrwRate() {
    const res = await fetch("https://api.upbit.com/v1/ticker?markets=KRW-USDT");
    if (!res.ok) throw new Error("USDT/KRW 환율 HTTP " + res.status);
    return (await res.json())[0].trade_price;
  }

  // 업비트가 요청이 몰리면 429를 CORS 헤더 없이 돌려준다 - 브라우저가
  // 상태코드를 읽기 전에 막아버려서 fetch()가 "Failed to fetch"로 뭉뚱그린다
  // (2026-09-15 실측). 그 창이 초 단위로 리셋되니 한 번 더 시도한다.
  async function withRetry(fn, retries) {
    try {
      return await fn();
    } catch (e) {
      if (retries <= 0) throw e;
      await new Promise((r) => setTimeout(r, 1200));
      return withRetry(fn, retries - 1);
    }
  }

  // 3개 출처(국내가·바이낸스가·USDT환율) 중 하나가 막혀도 나머지는 보여준다
  // - 하나만 실패해도 전체를 던지면 패널이 통째로 비었다(교훈57과 같은
  // 모양: 모르는 값이 하나 있다고 아는 값까지 숨기지 않는다).
  async function fetchAllTickers(exchange, codes) {
    let domesticR, binanceR, usdtKrwR;
    if (exchange === "upbit") {
      // 업비트 국내가·USDT환율을 한 호출로 합친다(markets에 KRW-USDT를 같이
      // 넣는다) - 따로 두 번 부르면 업비트의 초당 요청 한도에 둘이 같이
      // 걸려 가격은 뜨는데 환율만 실패하는 경우가 있었다(2026-09-15 실측).
      const [combinedR, binR] = await Promise.allSettled([
        withRetry(() => fetchUpbitTickers(codes.concat(["USDT"])), 1),
        withRetry(() => fetchBinanceUsdt(codes), 1),
      ]);
      domesticR = combinedR;
      binanceR = binR;
      usdtKrwR = (combinedR.status === "fulfilled" && combinedR.value.USDT)
        ? { status: "fulfilled", value: combinedR.value.USDT.price }
        : { status: "rejected" };
    } else {
      [domesticR, binanceR, usdtKrwR] = await Promise.allSettled([
        withRetry(() => fetchBithumbTickers(codes), 1),
        withRetry(() => fetchBinanceUsdt(codes), 1),
        withRetry(() => fetchUsdtKrwRate(), 1),
      ]);
    }
    const domestic = domesticR.status === "fulfilled" ? domesticR.value : {};
    const binance = binanceR.status === "fulfilled" ? binanceR.value : {};
    const usdtKrw = usdtKrwR.status === "fulfilled" ? usdtKrwR.value : null;
    const failedParts = [];
    if (domesticR.status === "rejected") failedParts.push((exchange === "upbit" ? "업비트" : "빗썸") + " 시세");
    if (binanceR.status === "rejected") failedParts.push("바이낸스 시세");
    if (usdtKrwR.status === "rejected" && domesticR.status === "fulfilled") failedParts.push("USDT/KRW 환율");
    return { domestic, binance, usdtKrw, failedParts };
  }

  // 업비트는 자체 캔들 API, 빗썸은 자체 캔들 API를 각각 쓴다(교차로 빌리지
  // 않는다) - 같은 코인이라도 두 거래소 가격이 갈릴 수 있어 탭이 보여주는
  // 시세와 다른 거래소 캔들을 섞으면 헷갈린다.
  async function fetchOhlc(exchange, code, timeframeId, count) {
    const tf = TIMEFRAMES.find((t) => t.id === timeframeId);
    if (exchange === "upbit") {
      const path = timeframeId === "1d" ? "days" : "minutes/" + tf.upbitUnit;
      const res = await fetch("https://api.upbit.com/v1/candles/" + path + "?market=KRW-" + code + "&count=" + count);
      if (!res.ok) throw new Error("업비트 차트 HTTP " + res.status);
      return (await res.json()).reverse().map((r) => ({
        time: Math.floor(new Date(r.candle_date_time_kst + "+09:00").getTime() / 1000),
        open: r.opening_price, high: r.high_price, low: r.low_price, close: r.trade_price,
      }));
    }
    const res = await fetch("https://api.bithumb.com/public/candlestick/" + code + "_KRW/" + tf.bithumbInterval);
    if (!res.ok) throw new Error("빗썸 차트 HTTP " + res.status);
    const j = await res.json();
    if (j.status !== "0000") throw new Error("빗썸 차트 응답 오류 (status " + j.status + ")");
    return j.data.slice(-count).map((r) => ({
      time: Math.floor(r[0] / 1000), open: Number(r[1]), close: Number(r[2]), high: Number(r[3]), low: Number(r[4]),
    }));
  }

  // 이동평균 - 닫힌 봉의 종가만 쓴다(진행 중인 마지막 봉 포함 여부로 값이
  // 흔들리지 않게 캔들 API가 준 값을 그대로 신뢰한다).
  function computeMA(bars, period) {
    const out = [];
    let sum = 0;
    for (let i = 0; i < bars.length; i++) {
      sum += bars[i].close;
      if (i >= period) sum -= bars[i - period].close;
      if (i >= period - 1) out.push({ time: bars[i].time, value: sum / period });
    }
    return out;
  }

  // TradingView 오픈소스 lightweight-charts(MIT) - 캔들·오버레이 렌더링을
  // 직접 짜지 않는다. 코인을 처음 클릭할 때만 불러온다(페이지 로드마다
  // 160KB를 얹지 않는다).
  let chartsLibPromise = null;
  function loadChartsLib() {
    if (window.LightweightCharts) return Promise.resolve(window.LightweightCharts);
    if (!chartsLibPromise) {
      chartsLibPromise = new Promise((resolve, reject) => {
        const s = document.createElement("script");
        s.src = "https://cdn.jsdelivr.net/npm/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js";
        s.onload = () => resolve(window.LightweightCharts);
        s.onerror = () => reject(new Error("차트 라이브러리 로드 실패(네트워크)"));
        document.head.appendChild(s);
      });
    }
    return chartsLibPromise;
  }

  // 한 번에 하나만 연다 - 여러 코인 차트를 동시에 띄우면 어느 게 어느
  // 프리미엄 행 아래 것인지 헷갈린다.
  let openChart = null; // { code, exchange, timeframeId, activeMAs, row, tr, lwChart, maSeries, bars, cleanupResize }

  function closeOpenChart() {
    if (!openChart) return;
    if (openChart.cleanupResize) openChart.cleanupResize();
    if (openChart.lwChart) openChart.lwChart.remove();
    if (openChart.row) openChart.row.style.background = "";
    if (openChart.tr) openChart.tr.remove();
    openChart = null;
  }

  async function drawChart(bodyEl) {
    const state = openChart;
    bodyEl.innerHTML = '<div class="empty">차트 불러오는 중...</div>';
    let LW, bars;
    try {
      [LW, bars] = await Promise.all([
        loadChartsLib(),
        withRetry(() => fetchOhlc(state.exchange, state.code, state.timeframeId, 200), 1),
      ]);
    } catch (e) {
      if (openChart === state) bodyEl.innerHTML = '<div class="empty">차트 조회 실패: ' + String((e && e.message) || e) + "</div>";
      return;
    }
    if (openChart !== state) return; // 로딩 중 닫히거나 다른 코인으로 바뀌었으면 그린다
    bodyEl.innerHTML = "";
    const chartEl = document.createElement("div");
    chartEl.style.width = "100%";
    chartEl.style.height = "280px";
    bodyEl.appendChild(chartEl);

    const chart = LW.createChart(chartEl, {
      width: chartEl.clientWidth, height: 280,
      layout: { background: { color: "transparent" }, textColor: cssVar("--text-dim", "#888") },
      grid: { vertLines: { visible: false }, horzLines: { color: "rgba(128,128,128,0.12)" } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: state.timeframeId !== "1d", secondsVisible: false },
    });
    const up = cssVar("--up", "#e0384a"), down = cssVar("--down", "#2f6fe0");
    const candleSeries = chart.addCandlestickSeries({
      upColor: up, downColor: down, borderVisible: false, wickUpColor: up, wickDownColor: down,
    });
    candleSeries.setData(bars);

    state.lwChart = chart;
    state.bars = bars;
    state.maSeries = {};
    MA_PERIODS.forEach((p) => {
      if (!state.activeMAs.has(p)) return;
      const s = chart.addLineSeries({ color: MA_COLORS[p], lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      s.setData(computeMA(bars, p));
      state.maSeries[p] = s;
    });
    chart.timeScale().fitContent();

    const onResize = () => { if (openChart === state) chart.applyOptions({ width: chartEl.clientWidth }); };
    window.addEventListener("resize", onResize);
    state.cleanupResize = () => window.removeEventListener("resize", onResize);
  }

  function toggleMA(period) {
    if (!openChart || !openChart.lwChart) return;
    if (openChart.activeMAs.has(period)) {
      openChart.activeMAs.delete(period);
      if (openChart.maSeries[period]) { openChart.lwChart.removeSeries(openChart.maSeries[period]); delete openChart.maSeries[period]; }
    } else {
      openChart.activeMAs.add(period);
      const s = openChart.lwChart.addLineSeries({ color: MA_COLORS[period], lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
      s.setData(computeMA(openChart.bars, period));
      openChart.maSeries[period] = s;
    }
  }

  function chartControlsHtml() {
    return '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:8px">' +
      '<div class="v-chip-row" data-role="tf" style="margin:0">' +
        TIMEFRAMES.map((t) => '<button class="v-chip" data-tf="' + t.id + '">' + t.label + "</button>").join("") +
      "</div>" +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
        '<div class="v-chip-row" data-role="ma" style="margin:0">' +
          MA_PERIODS.map((p) => '<button class="v-chip" data-ma="' + p + '" style="border-color:' + MA_COLORS[p] + '">MA' + p + "</button>").join("") +
        "</div>" +
        '<button class="v-chip" data-role="close">닫기 ✕</button>' +
      "</div></div>" +
      '<div data-role="body"><div class="empty">차트 불러오는 중...</div></div>';
  }

  function openInlineChart(row, code, exchange) {
    if (openChart && openChart.code === code) { closeOpenChart(); return; }
    closeOpenChart();

    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 4;
    td.style.padding = "12px 8px";
    td.style.background = "var(--surface-2, rgba(120,120,120,0.06))";
    td.innerHTML = chartControlsHtml();
    tr.appendChild(td);
    row.after(tr);
    row.style.background = "var(--surface-3)";

    openChart = { code, exchange, timeframeId: "1h", activeMAs: new Set(), row, tr, lwChart: null, maSeries: {}, bars: null };
    td.querySelector('[data-tf="1h"]').classList.add("active");
    td.querySelectorAll("[data-tf]").forEach((btn) => {
      btn.addEventListener("click", () => {
        if (!openChart) return;
        td.querySelectorAll("[data-tf]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        openChart.timeframeId = btn.dataset.tf;
        drawChart(td.querySelector('[data-role="body"]'));
      });
    });
    td.querySelectorAll("[data-ma]").forEach((btn) => {
      btn.addEventListener("click", () => {
        btn.classList.toggle("active");
        toggleMA(Number(btn.dataset.ma));
      });
    });
    td.querySelector('[data-role="close"]').addEventListener("click", closeOpenChart);

    tr.scrollIntoView({ behavior: "smooth", block: "center" });
    drawChart(td.querySelector('[data-role="body"]'));
  }

  function rowHtml(c) {
    return '<tr class="ct-row" data-code="' + c.code + '" style="cursor:pointer">' +
      "<td style='text-align:left'>" + c.name + " <span class='mono dim' style='font-size:11px'>" + c.code + "</span></td>" +
      '<td class="mono ct-price">—</td><td class="mono ct-change">—</td><td class="mono ct-premium">—</td></tr>';
  }

  function applyRowValues(container, c, domestic, binance, usdtKrw) {
    const PT = window.PT;
    const row = container.querySelector('tr.ct-row[data-code="' + c.code + '"]');
    if (!row) return;
    const d = domestic[c.code], b = binance[c.code];
    const premiumPct = (d && b && usdtKrw) ? ((d.price / (b * usdtKrw)) - 1) * 100 : null;
    row.querySelector(".ct-price").textContent = d ? PT.formatPrice(d.price) + "원" : "—";
    const changeCell = row.querySelector(".ct-change");
    changeCell.textContent = d ? PT.formatPnlPct(d.changePct) : "—";
    changeCell.className = "mono ct-change" + (d ? " " + PT.getPnlClass(d.changePct) : "");
    const premCell = row.querySelector(".ct-premium");
    premCell.textContent = premiumPct === null ? "—" : PT.formatPnlPct(premiumPct);
    premCell.className = "mono ct-premium" + (premiumPct === null ? "" : " " + PT.getPnlClass(premiumPct));
  }

  function infoLineText(usdtKrw, failedParts) {
    const PT = window.PT;
    let s = "USDT/KRW 기준환율(업비트) " + (usdtKrw ? PT.formatPrice(usdtKrw) + "원" : "—") +
      " · 해외가는 바이낸스 USDT 마켓 · 종목을 클릭하면 차트가 표시됩니다 · " + (REFRESH_MS / 1000) + "초마다 자동 갱신";
    if (failedParts.length) s += " · 조회 실패: " + failedParts.join(", ");
    return s;
  }

  function armRefresh(container, exchange) {
    refreshTimer = setInterval(() => {
      if (!container.offsetParent) { clearInterval(refreshTimer); refreshTimer = null; return; }
      renderPanel(container, exchange, true);
    }, REFRESH_MS);
  }

  async function renderPanel(container, exchange, isAutoRefresh) {
    if (refreshTimer) { clearInterval(refreshTimer); refreshTimer = null; }
    if (!isAutoRefresh) {
      closeOpenChart();
      container.innerHTML = '<div class="panel"><h2>시세 · 프리미엄</h2><div class="empty">불러오는 중...</div></div>';
    }

    const codes = COINS.map((c) => c.code);
    const { domestic, binance, usdtKrw, failedParts } = await fetchAllTickers(exchange, codes);
    const gotNothing = Object.keys(domestic).length === 0 && Object.keys(binance).length === 0 && !usdtKrw;

    if (gotNothing) {
      if (!isAutoRefresh) {
        container.innerHTML = '<div class="panel"><h2>시세 · 프리미엄</h2><div class="empty">시세 조회 실패(거래소 API 응답 없음) — 새로고침으로 다시 시도해주세요.</div></div>';
      }
      armRefresh(container, exchange); // 자동 갱신 중 실패면 이번 틱은 조용히 건너뛰고 화면은 그대로 둔다
      return;
    }

    const table = container.querySelector("table.ct-table");
    if (isAutoRefresh && table) {
      // 구조는 그대로 두고 숫자만 갱신 - 열려있는 인라인 차트를 건드리지 않는다.
      COINS.forEach((c) => applyRowValues(container, c, domestic, binance, usdtKrw));
      const infoEl = container.querySelector(".ct-info");
      if (infoEl) infoEl.textContent = infoLineText(usdtKrw, failedParts);
      armRefresh(container, exchange);
      return;
    }

    let html = '<div class="panel"><h2>시세 · 프리미엄</h2>' +
      '<div class="ct-info dim" style="font-size:11px;margin-bottom:8px">' + infoLineText(usdtKrw, failedParts) + "</div>" +
      '<table class="ct-table"><thead><tr><th>코인</th><th>현재가</th><th>24H 등락</th><th>프리미엄</th></tr></thead><tbody>';
    COINS.forEach((c) => { html += rowHtml(c); });
    html += "</tbody></table></div>";
    container.innerHTML = html;
    COINS.forEach((c) => applyRowValues(container, c, domestic, binance, usdtKrw));

    container.querySelectorAll(".ct-row").forEach((row) => {
      row.addEventListener("click", () => openInlineChart(row, row.dataset.code, exchange));
    });

    armRefresh(container, exchange);
  }

  return { renderPanel };
})();
