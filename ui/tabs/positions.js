/* Positions 탭 - 보유 종목 전체 표 + 종목 클릭 시 상세 모달(2026-09-14 개편).
   Signal(probability/expectancy 등)·Risk score는 이 엔진에 저장되지 않아
   모달에 안 넣는다 - 대신 실제로 계산 가능한 베타·연변동성(종가·코스피로
   계산)을 넣는다. */
window.TABS = window.TABS || {};
window.TABS.positions = {
  title: "Positions",
  render: async function (container) {
    const PT = window.PT;
    let data;
    try {
      data = await PT.fetchJson("data/positions.json");
    } catch (e) {
      container.innerHTML = '<div class="empty">데이터 로드 실패: ' + String(e.message || e) + "</div>";
      return;
    }
    const macro = await PT.tryFetchJson("data/macro.json");
    const tickerNames = (await PT.tryFetchJson("data/ticker-names.json")) || {};
    const series = macro && macro.series || {};
    const realign = (h) => (h || []).filter((x) => x.asOf).map((x) => ({ date: x.asOf, value: x.value }));
    const kospiHist = realign(series.krKospi && series.krKospi.history);

    const strategyEntries = Object.entries(data.strategies || {});
    const all = [];
    strategyEntries.forEach(([id, s]) => (s.positions || []).forEach((p) => all.push({ ...p, strategyId: id })));

    if (!all.length) {
      container.innerHTML = '<div class="panel"><h2>Positions</h2><div class="empty">현재 보유 포지션이 없습니다.</div></div>';
      return;
    }

    let html = '<div class="panel">';
    html += '<h2>전체 포지션 (' + all.length + '건)</h2>';
    html += '<div class="table-scroll" style="overflow-x:auto"><table><thead><tr>' +
      "<th>종목</th><th>전략</th><th>추이</th><th>상태</th><th>수량</th><th>평단가</th>" +
      "<th>현재가</th><th>평가금액</th><th>평가손익</th><th>수익률</th></tr></thead><tbody>";
    all.forEach((p) => {
      const name = tickerNames[p.symbol];
      html += '<tr class="pos-row" data-symbol="' + p.symbol + '" data-strategy="' + p.strategyId + '" style="cursor:pointer">' +
        "<td style='text-align:left'>" + (name ? name + ' <span class="mono dim" style="font-size:11px">' + p.symbol + "</span>" : '<span class="mono">' + p.symbol + "</span>") + "</td>" +
        '<td class="mono dim">' + p.strategyId + "</td>" +
        "<td>" + PT.sparklineSvg(p.history) + "</td>" +
        '<td><span class="badge ' + PT.getStatusBadgeClass(p.status) + '">' + p.status + "</span></td>" +
        '<td class="mono">' + (p.quantity ?? "-") + "</td>" +
        '<td class="mono">' + PT.formatPrice(p.avgEntryPrice) + "</td>" +
        '<td class="mono">' + PT.formatPrice(p.currentPrice) + "</td>" +
        '<td class="mono">' + (p.currentPrice ? PT.formatAccount(p.currentPrice * (p.quantity || 0)) : "-") + "</td>" +
        '<td class="mono ' + PT.getPnlClass(p.unrealizedPnlKrw) + '">' + PT.formatPnl(p.unrealizedPnlKrw) + "</td>" +
        '<td class="mono ' + PT.getPnlClass(p.unrealizedPnlPct) + '">' + PT.formatPnlPct(p.unrealizedPnlPct) + "</td>" +
        "</tr>";
    });
    html += "</tbody></table></div></div>";
    container.innerHTML = html;

    container.querySelectorAll(".pos-row").forEach((row) => {
      row.addEventListener("click", () => {
        const pos = all.find((p) => p.symbol === row.dataset.symbol && p.strategyId === row.dataset.strategy);
        if (pos) openDetailModal(pos, tickerNames[pos.symbol], kospiHist);
      });
      row.addEventListener("keydown", (e) => { if (e.key === "Enter") row.click(); });
      row.tabIndex = 0;
    });
  },
};

let posModalEl = null;
function closePosModal() {
  if (posModalEl) { posModalEl.remove(); posModalEl = null; document.removeEventListener("keydown", onPosModalKeydown); }
}
function onPosModalKeydown(e) { if (e.key === "Escape") closePosModal(); }

function openDetailModal(pos, name, kospiHist) {
  const PT = window.PT;
  closePosModal();
  const risk = PT.computeRiskMetrics(pos.history, kospiHist);

  posModalEl = document.createElement("div");
  posModalEl.className = "rl-modal-backdrop";
  posModalEl.innerHTML =
    '<div class="rl-modal panel" role="dialog" aria-modal="true" aria-label="' + pos.symbol + ' 상세">' +
    '  <div class="rl-modal-head"><div class="finding-title">' + (name || pos.symbol) +
    '    <span class="mono dim" style="font-size:12px">' + pos.symbol + "</span></div>" +
    '  <button type="button" class="rl-modal-close" aria-label="닫기">&times;</button></div>' +
    '  <div class="rl-modal-body">' +
    '    <div class="kpi-grid" style="grid-template-columns:repeat(auto-fit,minmax(130px,1fr))">' +
    kpiMini("현재가", PT.formatPrice(pos.currentPrice) + "원") +
    kpiMini("수익률", PT.formatPnlPct(pos.unrealizedPnlPct), PT.getPnlClass(pos.unrealizedPnlPct)) +
    kpiMini("평가손익", PT.formatPnl(pos.unrealizedPnlKrw) + "원", PT.getPnlClass(pos.unrealizedPnlKrw)) +
    kpiMini("전략", pos.strategyId) +
    kpiMini("보유수량", (pos.quantity ?? "-") + "주") +
    kpiMini("평균단가", PT.formatPrice(pos.avgEntryPrice) + "원") +
    kpiMini("평가금액", pos.currentPrice ? PT.formatAccount(pos.currentPrice * (pos.quantity || 0)) + "원" : "—") +
    kpiMini("상태", pos.status) +
    "    </div>" +
    '    <h2 style="margin:16px 0 8px">리스크 (베타·연변동성)</h2>' +
    '    <div class="dim" style="font-size:11.5px;margin-bottom:8px">종목 종가와 코스피로 계산 — ' +
    "확률(probability_up)·기대수익(expectancy)·손절가 같은 예측값은 이 엔진이 저장하지 않아 표시하지 않습니다.</div>" +
    (risk
      ? '<div class="kpi-grid" style="grid-template-columns:repeat(auto-fit,minmax(130px,1fr))">' +
        kpiMini("Beta (vs 코스피)", risk.beta != null ? risk.beta.toFixed(2) : "—") +
        kpiMini("연환산 변동성", risk.volAnnualPct.toFixed(1) + "%") +
        kpiMini("표본일수", risk.n + "일") + "</div>"
      : '<div class="empty" style="padding:12px">겹치는 거래일이 20일 미만이라 계산하지 않습니다.</div>') +
    "  </div></div>";

  posModalEl.addEventListener("click", (e) => { if (e.target === posModalEl) closePosModal(); });
  posModalEl.querySelector(".rl-modal-close").addEventListener("click", closePosModal);
  document.body.appendChild(posModalEl);
  document.addEventListener("keydown", onPosModalKeydown);
  posModalEl.querySelector(".rl-modal-close").focus();
}

function kpiMini(label, value, pnlClass) {
  return '<div class="kpi-card"><div class="kpi-label">' + label + '</div>' +
    '<div class="kpi-value mono ' + (pnlClass || "") + '" style="font-size:16px">' + value + "</div></div>";
}
