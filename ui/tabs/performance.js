/* Performance 탭 - equity-history.json(일별 총평가액)과 trades.days(일별
   실현손익)로 프론트에서 직접 계산한다(2026-09-14 개편). 새 파이프라인
   없음 - 이미 있는 raw 데이터를 브라우저에서 집계만 한다.
   ★ 이력이 짧다(계좌 곡선을 하루 한 줄로 쌓기 시작한 지 얼마 안 됨) -
   숫자는 계산되지만 통계적으로 큰 의미가 없을 수 있어 표본일수를 항상
   같이 보여준다("정직한 점수" 원칙, 절대 규칙 1과 같은 취지). */
window.TABS = window.TABS || {};
window.TABS.performance = {
  title: "Performance",
  render: async function (container) {
    const PT = window.PT;
    const posData = await PT.tryFetchJson("data/positions.json");
    const equity = await PT.tryFetchJson("data/equity-history.json");
    const hist = (equity && equity.history) || [];

    let html = '<div class="panel"><h2>계좌 성과</h2>';
    html += '<div class="dim" style="font-size:11.5px;margin-bottom:10px">' +
      (hist.length ? "표본 " + hist.length + "일(" + hist[0].date + " ~ " + hist[hist.length - 1].date + ") — " : "") +
      "이력이 짧으면 CAGR·Sharpe 같은 연환산 지표는 통계적으로 큰 의미가 없습니다. 표본일수를 항상 같이 보세요.</div>";
    html += metricsHtml(hist);
    html += "</div>";
    html += tradeStatsHtml(posData && posData.trades, PT);
    html += strategyPerfHtml(posData && posData.strategies, PT);
    container.innerHTML = html;
  },
};

function metricsHtml(hist) {
  const PT = window.PT;
  const kpi = (label, value) => '<div class="kpi-card"><div class="kpi-label">' + label + '</div><div class="kpi-value mono">' + value + "</div></div>";

  if (hist.length < 2) {
    return '<div class="kpi-grid">' + kpi("누적수익률", "—") + kpi("CAGR", "—") + kpi("MDD", "—") + kpi("Sharpe", "—") +
      '</div><div class="empty">계좌 자산 이력이 아직 2일치가 안 됩니다.</div>';
  }

  const first = hist[0], last = hist[hist.length - 1];
  const cumRet = (last.totalKrw / first.totalKrw - 1) * 100;
  const days = (new Date(last.date) - new Date(first.date)) / 86400000;
  const cagr = days > 0 ? (Math.pow(last.totalKrw / first.totalKrw, 365 / days) - 1) * 100 : null;

  let peak = hist[0].totalKrw, mdd = 0;
  const rets = [];
  for (let i = 1; i < hist.length; i++) {
    peak = Math.max(peak, hist[i].totalKrw);
    mdd = Math.min(mdd, (hist[i].totalKrw - peak) / peak);
    rets.push(hist[i].totalKrw / hist[i - 1].totalKrw - 1);
  }
  const meanRet = rets.reduce((a, b) => a + b, 0) / rets.length;
  const variance = rets.reduce((a, b) => a + (b - meanRet) ** 2, 0) / rets.length;
  const stdRet = Math.sqrt(variance);
  const sharpe = stdRet > 0 ? (meanRet / stdRet) * Math.sqrt(252) : null;

  return '<div class="kpi-grid">' +
    '<div class="kpi-card"><div class="kpi-label">누적수익률</div><div class="kpi-value mono ' + PT.getPnlClass(cumRet) + '">' + PT.formatPnlPct(cumRet) + "</div></div>" +
    '<div class="kpi-card"><div class="kpi-label">CAGR (연환산)</div><div class="kpi-value mono ' + (cagr === null ? "" : PT.getPnlClass(cagr)) + '">' + (cagr === null ? "—" : PT.formatPnlPct(cagr)) + "</div></div>" +
    '<div class="kpi-card"><div class="kpi-label">MDD</div><div class="kpi-value mono down">' + (mdd * 100).toFixed(2) + "%</div></div>" +
    '<div class="kpi-card"><div class="kpi-label">Sharpe</div><div class="kpi-value mono">' + (sharpe === null ? "—" : sharpe.toFixed(2)) + "</div></div>" +
    "</div>";
}

// 승률·평균손익은 "거래별"이 아니라 "일별 실현손익" 단위다 - 원장이 개별
// 체결의 진입가를 다 못 살리는 날은 "기록없음"으로 빠지므로(realizedFrom),
// 그 날은 통계에서 뺀다(0으로 채우지 않는다).
function tradeStatsHtml(trades, PT) {
  const days = (trades && trades.days) || [];
  const realizedDays = days.filter((d) => d.realizedFrom > 0);
  const buyCount = days.reduce((a, d) => a + (d.buyCount || 0), 0);
  const sellCount = days.reduce((a, d) => a + (d.sellCount || 0), 0);

  let html = '<div class="panel" style="margin-top:12px"><h2>매매 통계 <span class="dim" style="font-size:11px;font-weight:400">— 일별 실현손익 기준(개별 체결 단위 아님)</span></h2>';
  html += '<div class="kpi-grid">' +
    '<div class="kpi-card"><div class="kpi-label">총 매수/매도 건수</div><div class="kpi-value mono">' + buyCount + " / " + sellCount + "</div></div>";

  if (!realizedDays.length) {
    html += '<div class="kpi-card"><div class="kpi-label">승률</div><div class="kpi-value mono">—</div></div></div>';
    html += '<div class="dim" style="font-size:11.5px;margin-top:8px">진입가가 남아있는(원장 도입 이후) 실현손익 기록이 아직 없습니다.</div></div>';
    return html;
  }
  const wins = realizedDays.filter((d) => d.realizedKrw > 0);
  const losses = realizedDays.filter((d) => d.realizedKrw <= 0);
  const winRate = (wins.length / realizedDays.length) * 100;
  const avgWin = wins.length ? wins.reduce((a, d) => a + d.realizedKrw, 0) / wins.length : null;
  const avgLoss = losses.length ? losses.reduce((a, d) => a + d.realizedKrw, 0) / losses.length : null;

  html += '<div class="kpi-card"><div class="kpi-label">승률(일 단위)</div><div class="kpi-value mono">' + winRate.toFixed(1) + "%</div>" +
    '<div class="kpi-sub">' + wins.length + "승 " + losses.length + "패 / " + realizedDays.length + "일</div></div>" +
    '<div class="kpi-card"><div class="kpi-label">평균 이익일</div><div class="kpi-value mono up">' + (avgWin === null ? "—" : PT.formatPnl(avgWin) + "원") + "</div></div>" +
    '<div class="kpi-card"><div class="kpi-label">평균 손실일</div><div class="kpi-value mono down">' + (avgLoss === null ? "—" : PT.formatPnl(avgLoss) + "원") + "</div></div>" +
    "</div></div>";
  return html;
}

function strategyPerfHtml(strategies, PT) {
  const entries = Object.entries(strategies || {});
  let html = '<div class="panel" style="margin-top:12px"><h2>전략별 성과 <span class="dim" style="font-size:11px;font-weight:400">— 현재 미실현손익 기준</span></h2>';
  if (!entries.length) return html + '<div class="empty">등록된 전략이 없습니다.</div></div>';

  html += '<table><thead><tr><th>전략</th><th>미실현손익</th><th>수익률</th><th>보유종목수</th></tr></thead><tbody>';
  entries.forEach(([id, s]) => {
    const t = PT.strategyTotals(s.positions);
    const openCount = (s.positions || []).filter((p) => p.status === "OPEN").length;
    html += "<tr><td style='text-align:left'>" + id + "</td>" +
      '<td class="mono ' + (t.cost ? PT.getPnlClass(t.pnl) : "dim") + '">' + (t.cost ? PT.formatPnl(t.pnl) + "원" : "—") + "</td>" +
      '<td class="mono ' + (t.cost ? PT.getPnlClass(t.pnlPct) : "dim") + '">' + (t.cost ? PT.formatPnlPct(t.pnlPct) : "—") + "</td>" +
      '<td class="mono">' + openCount + " / " + (s.positions || []).length + "</td></tr>";
  });
  html += "</tbody></table></div>";
  return html;
}
