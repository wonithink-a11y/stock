/* System 탭 - 데이터 소스별 최신성 + 브로커 연결상태(2026-09-14 개편).
   ★ 라이브 헬스체크가 없다 - "KIS Connected"를 실측 없이 "정상"이라고
   보여주지 않는다. 확인 가능한 건 "마지막으로 받은 데이터가 언제인지"뿐이라
   그것만 정직하게 보여준다. RV20 선물·업비트·빗썸은 KIS 국내주식과 다른
   브로커라 별도 섹션("다른 브로커")으로 둔다 - Overview KPI엔 안 섞는다. */
window.TABS = window.TABS || {};
window.TABS.system = {
  title: "System",
  render: async function (container) {
    const PT = window.PT;
    const positions = await PT.tryFetchJson("data/positions.json");
    const equity = await PT.tryFetchJson("data/equity-history.json");
    const macro = await PT.tryFetchJson("data/macro.json");
    const rv20 = await PT.tryFetchJson("data/rv20-futures-automation.json");
    let real = null;
    try {
      const r = await fetch("https://wonithink-stock.duckdns.org/accounts?t=" + Date.now());
      if (r.ok) real = (await r.json()).real;
    } catch (e) { /* 카드 생략 */ }

    container.innerHTML =
      dataSourcesCardHtml(positions, equity, macro) +
      kisStatusCardHtml(positions) +
      otherBrokersCardHtml(rv20, real) +
      overseasCardHtml(positions && positions.overseas);
  },
};

// 해외 슬리브(TQQQ·SOXL 분할매수 사이클) - KIS 해외계좌라 통화(USD)도 다르고
// 국내주식 KPI와 합산할 수 없다. chart.js에 있던 표를 그대로 옮겼다(vts=실제
// 주문이 나간 것, paper=규칙대로(LOC) 돈 것 - KIS 모의투자가 지정가만 받아
// 갈라진다, 실측: 사이클 45%↓·MDD 6~9%p↑).
function overseasCardHtml(overseas) {
  const PT = window.PT;
  if (!overseas || !(overseas.sleeves || []).length) return "";
  const usd = (v, d) => v === null || v === undefined ? "—" :
    "$" + v.toLocaleString("en-US", { minimumFractionDigits: d === undefined ? 2 : d, maximumFractionDigits: d === undefined ? 2 : d });

  let out = '<div class="panel" style="margin-top:12px"><h2>해외 슬리브 — 분할매수 사이클 (TQQQ · SOXL) ' +
    '<span class="dim" style="font-size:11px;font-weight:400">— Overview 총자산에 합산하지 않음</span></h2>';
  if (overseas.error) {
    out += '<div class="dim" style="margin-bottom:8px">계좌 조회 실패 — 저장된 상태만 표시합니다: ' + String(overseas.error) + "</div>";
  }
  out += '<div class="dim" style="font-size:11.5px;margin-bottom:8px"><b>vts</b> = 모의계좌 실주문(지정가만) · <b>paper</b> = 규칙대로(LOC) 돈 전략 판정용 정본. 두 숫자는 갈라지는 게 정상입니다.</div>';
  out += '<div style="overflow-x:auto"><table><thead><tr><th>종목</th><th>모드</th><th>회차 T</th><th>보유</th><th>평단</th><th>현재가</th><th>평가손익</th></tr></thead><tbody>';
  overseas.sleeves.slice().sort((a, b) => a.ticker.localeCompare(b.ticker) || a.mode.localeCompare(b.mode)).forEach((s) => {
    out += "<tr><td><b>" + s.ticker + "</b></td><td class=\"mono\">" + s.mode + "</td>" +
      '<td class="mono">' + s.t.toFixed(2) + "</td><td class=\"mono\">" + s.qty + "주</td>" +
      '<td class="mono">' + usd(s.avgPriceUsd) + "</td><td class=\"mono\">" + usd(s.lastPriceUsd) + "</td>" +
      '<td class="mono ' + PT.getPnlClass(s.pnlUsd) + '">' + usd(s.pnlUsd) + "</td></tr>";
  });
  out += "</tbody></table></div></div>";
  return out;
}

function ageLabel(iso) {
  if (!iso) return { text: "—", warn: false };
  const t = new Date(iso).getTime();
  if (isNaN(t)) return { text: iso, warn: false };
  const hrs = (Date.now() - t) / 3600000;
  const text = hrs < 1 ? Math.round(hrs * 60) + "분 전" : hrs < 48 ? hrs.toFixed(1) + "시간 전" : (hrs / 24).toFixed(1) + "일 전";
  return { text, warn: hrs > 24 };
}

function dataSourcesCardHtml(positions, equity, macro) {
  const sources = [
    { name: "positions.json (계좌·포지션)", iso: positions && positions.updatedAt },
    { name: "equity-history.json (자산 추이)", iso: equity && equity.updatedAt },
    { name: "macro.json (벤치마크 지수)", iso: macro && macro.seriesAsOf },
  ];
  let html = '<div class="panel"><h2>데이터 최신성</h2>';
  sources.forEach((s) => {
    const a = ageLabel(s.iso);
    html += '<div class="sys-source-row"><span class="sys-source-name">' + s.name + "</span>" +
      '<span class="sys-source-age' + (a.warn ? " warn" : "") + '">' + (s.iso || "—") + " (" + a.text + ")</span></div>";
  });
  return html + "</div>";
}

// "계좌 조회: 정상/실패"는 실측이 아니라 positions.json 생성 시점에 KIS
// 응답을 받았는지의 흔적(account 필드 존재 여부)이다 - 지금 이 순간
// 연결돼 있다는 뜻이 아니다. 라이브 핑은 이 정적 사이트에서 할 수 없다.
function kisStatusCardHtml(positions) {
  const ok = !!(positions && positions.account);
  let html = '<div class="panel" style="margin-top:12px"><h2>KIS 모의투자(VTS) 상태</h2>';
  html += '<div class="dim" style="font-size:11.5px;margin-bottom:8px">실시간 연결 확인(라이브 헬스체크)은 이 정적 페이지에서 할 수 없습니다 — 마지막 데이터 생성 시점의 결과만 보여줍니다.</div>';
  html += '<div class="sys-source-row"><span class="sys-source-name">계좌 조회(최근 생성 시점)</span>' +
    '<span class="pill ' + (ok ? "pill-good" : "pill-bad") + '"><span class="pill-dot"></span>' + (ok ? "정상" : "실패") + "</span></div>";
  html += '<div class="sys-source-row"><span class="sys-source-name">체결내역 조회(최근 생성 시점)</span>' +
    '<span class="pill ' + (positions && positions.trades && !positions.trades.error ? "pill-good" : "pill-bad") + '"><span class="pill-dot"></span>' +
    (positions && positions.trades && !positions.trades.error ? "정상" : "실패") + "</span></div>";
  html += '<div class="sys-source-row"><span class="sys-source-name">주문 실행(Paper Engine 스캐너·폴러)</span>' +
    '<span class="pill pill-dim"><span class="pill-dot"></span>마지막 실행시각 미공개(로그가 VM에만 있음)</span></div>';
  return html + "</div>";
}

function otherBrokersCardHtml(rv20, real) {
  const PT = window.PT;
  const won = (v) => v === null || v === undefined ? "—" : PT.formatAccount(v) + "원";
  let html = '<div class="panel" style="margin-top:12px"><h2>다른 브로커 <span class="dim" style="font-size:11px;font-weight:400">— Overview 총자산에 합산하지 않음</span></h2>';

  const on = !!(rv20 && rv20.enabled);
  html += '<div class="sys-source-row"><span class="sys-source-name">RV20 선물 모의주문 자동실행</span>' +
    '<span class="pill ' + (on ? "pill-good" : "pill-dim") + '"><span class="pill-dot"></span>' + (on ? "켜짐" : "꺼짐") + "</span></div>";

  const realEntries = [{ key: "upbit", label: "업비트 실계좌" }, { key: "bithumb", label: "빗썸 실계좌" }];
  realEntries.forEach(({ key, label }) => {
    const d = real && real[key];
    html += '<div class="sys-source-row"><span class="sys-source-name">' + label + "</span>" +
      (d
        ? '<span class="mono">' + won(d.totalKrw) + '</span> <span class="pill pill-good" style="margin-left:8px"><span class="pill-dot"></span>정상</span>'
        : '<span class="pill pill-dim"><span class="pill-dot"></span>데이터 없음</span>') + "</div>";
  });
  return html + "</div>";
}
