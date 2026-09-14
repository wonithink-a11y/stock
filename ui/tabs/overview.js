/* Overview 탭 - 계좌 상태를 5~10초 안에 파악하는 첫 화면(2026-09-14 전면 개편).
   1차 버전은 KIS 국내주식 Paper Trading/VTS만 대상 - RV20 선물·업비트·빗썸은
   여기 KPI에 안 섞는다(System 탭에 별도 "다른 브로커" 섹션으로 둔다).
   데이터: ui/data/positions.json(account/strategies/trades) + equity-history.json
   (계좌 자산 추이) + macro.json(코스피·코스닥 벤치마크). */
window.TABS = window.TABS || {};
window.TABS.overview = {
  title: "Overview",
  render: async function (container) {
    const PT = window.PT;
    let data;
    try {
      data = await PT.fetchJson("data/positions.json");
    } catch (e) {
      container.innerHTML = /404/.test(String(e.message))
        ? '<div class="empty">Paper Trading 계좌 데이터(<code>data/positions.json</code>)가 이 배포본에 없습니다.<br>' +
          '<span class="dim">다른 탭은 정상 동작합니다.</span></div>'
        : '<div class="empty">데이터 로드 실패: ' + String(e.message || e) + "</div>";
      return;
    }
    const equity = await PT.tryFetchJson("data/equity-history.json");
    const macro = await PT.tryFetchJson("data/macro.json");

    const { account, strategies, trades, updatedAt, historyAsOf } = data;
    const strategyEntries = Object.entries(strategies || {});
    const eqHistory = (equity && equity.history) || [];

    container.innerHTML =
      kpiGridHtml(account, eqHistory) +
      '<div class="grid grid-2">' +
        equityChartCardHtml(eqHistory, macro) +
        strategyStatusCardHtml(strategyEntries, account) +
      "</div>" +
      '<div class="grid grid-2">' +
        positionsSummaryCardHtml(strategyEntries) +
        recentActivityCardHtml(trades) +
      "</div>";

    wireEquityChart(eqHistory, macro);
  },
};

function kpiGridHtml(account, eqHistory) {
  const PT = window.PT;
  const won = (v) => v === null || v === undefined ? "—" : PT.formatAccount(v) + "원";
  const total = account ? account.totalValueKrw : null;

  // 오늘 손익 = 이력의 마지막-직전 일 차이. 누적손익 = 이력 시작일 대비
  // (계좌 개설 이후 누적이 아니다 - equity-history가 2026-09-11부터 쌓이기
  // 시작했으므로, 기록 시작 전 손익은 알 수 없다. "누적"이라는 말이
  // 오해를 부르지 않게 캡션으로 밝힌다).
  let todayPnl = null, todayPnlPct = null, cumPnl = null, cumPnlPct = null, sinceDate = null;
  if (eqHistory.length >= 2) {
    const last = eqHistory[eqHistory.length - 1], prev = eqHistory[eqHistory.length - 2];
    todayPnl = last.totalKrw - prev.totalKrw;
    todayPnlPct = prev.totalKrw ? (todayPnl / prev.totalKrw) * 100 : null;
    const first = eqHistory[0];
    cumPnl = last.totalKrw - first.totalKrw;
    cumPnlPct = first.totalKrw ? (cumPnl / first.totalKrw) * 100 : null;
    sinceDate = first.date;
  }
  const investedPct = (account && account.totalValueKrw && account.stockValueKrw != null)
    ? (account.stockValueKrw / account.totalValueKrw) * 100 : null;

  const card = (label, value, sub, pnlClass) =>
    '<div class="kpi-card"><div class="kpi-label">' + label + '</div>' +
    '<div class="kpi-value mono ' + (pnlClass || "") + '">' + value + "</div>" +
    (sub ? '<div class="kpi-sub">' + sub + "</div>" : "") + "</div>";

  return '<div class="kpi-grid">' +
    card("총자산", won(total), historyAsOfSub(account)) +
    card("오늘 손익", todayPnl === null ? "—" : PT.formatPnl(todayPnl) + "원",
      todayPnlPct === null ? "" : PT.formatPnlPct(todayPnlPct), PT.getPnlClass(todayPnl)) +
    card("누적 손익", cumPnl === null ? "—" : PT.formatPnl(cumPnl) + "원",
      cumPnl === null ? "이력 부족" : sinceDate + " 기록 시작 대비 · " + PT.formatPnlPct(cumPnlPct), PT.getPnlClass(cumPnl)) +
    card("현금", won(account && account.cashKrw),
      account && account.cashAvailableKrw != null ? "가용(D+2) " + PT.formatAccount(account.cashAvailableKrw) + "원" : "") +
    card("투자비중", investedPct === null ? "—" : investedPct.toFixed(1) + "%",
      account && account.stockValueKrw != null ? "주식 " + PT.formatAccount(account.stockValueKrw) + "원" : "") +
    "</div>";
}

function historyAsOfSub() { return ""; }

function equityChartCardHtml() {
  return '<div class="panel">' +
    '  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">' +
    '    <h2 style="margin:0">계좌 자산 추이</h2>' +
    '    <div id="eq-period-group" class="v-chip-row" style="margin:0">' +
    '      <button class="v-chip" data-days="7">1W</button>' +
    '      <button class="v-chip active" data-days="30">1M</button>' +
    '      <button class="v-chip" data-days="0">전체</button>' +
    "    </div>" +
    "  </div>" +
    '  <div id="eq-chart-slot"></div>' +
    "</div>";
}

// 벤치마크 비교 - 코스피·코스닥·내 계좌를 공통 시작일=100으로 정규화해
// 한 그림에 겹친다(chart.js의 benchmarkPanelHtml과 같은 방식, 재사용).
// 절대수준이 자릿수가 달라(지수 2,500 vs 계좌 5억) 같은 축에 못 놓는다.
function wireEquityChart(eqHistory, macro) {
  const slot = document.getElementById("eq-chart-slot");
  const group = document.getElementById("eq-period-group");
  if (!slot) return;
  const series = macro && macro.series || {};
  const realign = (h) => (h || []).filter((x) => x.asOf).map((x) => ({ date: x.asOf, value: x.value }));
  const kospi = realign(series.krKospi && series.krKospi.history);
  const kosdaq = realign(series.krKosdaq && series.krKosdaq.history);

  function draw(days) {
    const cutoff = days > 0 && eqHistory.length
      ? eqHistory[Math.max(0, eqHistory.length - days)].date : null;
    const filt = (rows) => cutoff ? rows.filter((r) => r.date >= cutoff) : rows;
    slot.innerHTML = benchmarkChartHtml(filt(kospi), filt(kosdaq), filt(eqHistory));
  }
  if (group) {
    group.querySelectorAll(".v-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        group.querySelectorAll(".v-chip").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        draw(parseInt(btn.dataset.days, 10));
      });
    });
  }
  draw(30);
}

function benchmarkChartHtml(kospi, kosdaq, equity) {
  const PT = window.PT;
  const series = [
    { label: "코스피", color: "var(--accent)", rows: (kospi || []).map((h) => ({ date: h.date, v: h.value })) },
    { label: "코스닥", color: "var(--warn)", rows: (kosdaq || []).map((h) => ({ date: h.date, v: h.value })) },
    { label: "내 계좌", color: "var(--good)", rows: (equity || []).map((h) => ({ date: h.date, v: h.totalKrw })) },
  ].filter((s) => s.rows.length >= 2);
  if (!series.length) return '<div class="empty">자산 이력이 아직 충분하지 않습니다.</div>';

  const acct = series.find((s) => s.label === "내 계좌");
  const start = acct ? acct.rows[0].date : series[0].rows[0].date;
  const norm = series.map((s) => {
    const rows = s.rows.filter((r) => r.date >= start && r.v);
    const base = rows.length ? rows[0].v : null;
    return { ...s, pts: base ? rows.map((r) => ({ date: r.date, y: (r.v / base) * 100 })) : [] };
  }).filter((s) => s.pts.length >= 2);
  if (!norm.length) return '<div class="empty">자산 이력이 아직 충분하지 않습니다.</div>';

  const w = 900, h = 260, pad = 34;
  const dates = [...new Set(norm.flatMap((s) => s.pts.map((p) => p.date)))].sort();
  const xOf = (d) => pad + (dates.indexOf(d) / Math.max(1, dates.length - 1)) * (w - pad * 2);
  const ys = norm.flatMap((s) => s.pts.map((p) => p.y));
  const lo = Math.min(100, ...ys), hi = Math.max(100, ...ys), span = hi - lo || 1;
  const yOf = (v) => h - pad - ((v - lo) / span) * (h - pad * 2);

  let svg = '<svg viewBox="0 0 ' + w + " " + h + '" style="width:100%;height:auto" preserveAspectRatio="none">';
  svg += '<line x1="' + pad + '" y1="' + yOf(100) + '" x2="' + (w - pad) + '" y2="' + yOf(100) +
    '" style="stroke:var(--text-dim);stroke-width:1;stroke-dasharray:4 4;opacity:.5" />';
  norm.forEach((s) => {
    svg += '<polyline points="' + s.pts.map((p) => xOf(p.date).toFixed(1) + "," + yOf(p.y).toFixed(1)).join(" ") +
      '" fill="none" style="stroke:' + s.color + ';stroke-width:2;stroke-linejoin:round" />';
  });
  svg += "</svg>";

  const legend = norm.map((s) => {
    const raw = s.rows.filter((r) => r.date >= start && r.v);
    const a = raw[0].v, b = raw[raw.length - 1].v;
    const pct = (b / a - 1) * 100;
    const fmt = (v) => v >= 1e8 ? (v / 1e8).toFixed(2) + "억" : PT.formatPrice(Math.round(v * 100) / 100);
    return '<tr><td><span class="legend-dot" style="display:inline-block;background:' + s.color + '"></span> ' +
      s.label + '</td><td class="mono dim">' + fmt(a) + "</td><td class='dim'>→</td>" +
      '<td class="mono">' + fmt(b) + '</td><td class="mono ' + PT.getPnlClass(pct) + '" style="font-weight:700">' +
      PT.formatPnlPct(pct) + "</td></tr>";
  }).join("");

  return '<div class="dim mono" style="font-size:11px;margin-bottom:4px">기준일 ' + start + " · 일별 데이터(장중 실시간 아님) · " + dates.length + "일</div>" +
    svg + '<table class="bench-legend" style="font-size:12px;margin-top:6px;width:auto">' + legend + "</table>";
}

// 전략 상태 - ACTIVE/WAITING/ERROR라는 개념은 저장되지 않는다(엔진이 그런
// 상태를 안 남김). 대신 실제로 있는 포지션 status에서 정직하게 유도한다.
function strategyStatusCardHtml(strategyEntries, account) {
  const PT = window.PT;
  const total = account && account.totalValueKrw;
  let html = '<div class="panel"><h2>전략 상태</h2>';
  if (!strategyEntries.length) return html + '<div class="empty">등록된 전략이 없습니다.</div></div>';

  strategyEntries.forEach(([id, strategy]) => {
    const positions = strategy.positions || [];
    const t = PT.strategyTotals(positions);
    const openCount = positions.filter((p) => p.status === "OPEN").length;
    const pendingCount = positions.filter((p) => p.status === "PENDING_ENTRY" || p.status === "ENTRY_SUBMITTED").length;
    const exposurePct = total ? (t.value / total) * 100 : null;
    let statusLabel = "포지션 없음", statusClass = "pill-dim";
    if (pendingCount > 0) { statusLabel = "진입 대기 " + pendingCount + "건"; statusClass = "pill-warn"; }
    else if (openCount > 0) { statusLabel = "보유 중"; statusClass = "pill-good"; }

    html += '<div class="ov-strategy-card">' +
      '<div class="ov-strategy-head"><span class="ov-strategy-name">' + id + '</span>' +
      '<span class="pill ' + statusClass + '">' + statusLabel + "</span></div>";
    html += '<div class="ov-exposure-track"><div class="ov-exposure-fill" style="width:' +
      (exposurePct === null ? 0 : Math.min(100, exposurePct).toFixed(1)) + '%"></div></div>';
    html += '<div class="ov-strategy-meta">' +
      '<span>노출 ' + (exposurePct === null ? "—" : exposurePct.toFixed(1) + "%") + "</span>" +
      "<span>보유 " + openCount + " / " + positions.length + "건</span>" +
      (t.cost ? '<span class="' + PT.getPnlClass(t.pnl) + '">평가손익 ' + PT.formatPnl(t.pnl) + "원 (" + PT.formatPnlPct(t.pnlPct) + ")</span>" : "") +
      "</div></div>";
  });
  return html + "</div>";
}

function positionsSummaryCardHtml(strategyEntries) {
  const PT = window.PT;
  const all = [];
  strategyEntries.forEach(([id, s]) => (s.positions || []).forEach((p) => all.push({ ...p, strategyId: id })));
  const open = all.filter((p) => p.currentPrice != null).sort((a, b) =>
    (b.currentPrice * (b.quantity || 0)) - (a.currentPrice * (a.quantity || 0)));

  let html = '<div class="panel"><h2>보유 포지션 (평가금액 상위)</h2>';
  if (!open.length) return html + '<div class="empty">현재 보유 포지션이 없습니다.</div></div>';

  html += '<table><thead><tr><th>종목</th><th>전략</th><th>수량</th><th>평가금액</th><th>평가손익</th></tr></thead><tbody>';
  open.slice(0, 6).forEach((p) => {
    html += "<tr><td style='text-align:left'>" + p.symbol + "</td><td class='mono dim'>" + p.strategyId + "</td>" +
      '<td class="mono">' + (p.quantity ?? "-") + "</td>" +
      '<td class="mono">' + PT.formatAccount(p.currentPrice * (p.quantity || 0)) + "</td>" +
      '<td class="mono ' + PT.getPnlClass(p.unrealizedPnlKrw) + '">' + PT.formatPnl(p.unrealizedPnlKrw) +
      " (" + PT.formatPnlPct(p.unrealizedPnlPct) + ")</td></tr>";
  });
  html += "</tbody></table>";
  if (open.length > 6) html += '<div class="dim" style="font-size:11px;margin-top:6px">전체 ' + open.length + '건 — Positions 탭에서 확인</div>';
  return html + "</div>";
}

// "최근 신호"는 저장이 안 되므로(엔진이 방향/확률을 남기지 않음) 실제로
// 존재하는 가장 가까운 정보인 "오늘 낸 주문"을 정직하게 보여준다.
function recentActivityCardHtml(trades) {
  const PT = window.PT;
  let html = '<div class="panel"><h2>최근 주문 <span class="dim" style="font-size:11px;font-weight:400">— 신호(방향·확률 예측)는 이 엔진이 기록하지 않습니다, 실제 접수된 주문만 표시</span></h2>';
  const pending = (trades && trades.pending) || [];
  if (!pending.length) return html + '<div class="empty">최근 주문 없음</div></div>';

  html += '<table><thead><tr><th>일자</th><th>구분</th><th>종목</th><th>전략</th><th>주문/체결</th></tr></thead><tbody>';
  pending.slice(0, 6).forEach((o) => {
    html += "<tr><td class='mono'>" + o.date + "</td>" +
      '<td><span class="badge ' + (o.side === "SELL" ? "status-submitted" : "status-pending") + '">' +
      (o.side === "SELL" ? "매도" : "매수") + "</span></td>" +
      "<td style='text-align:left'>" + (o.name || o.symbol) + "</td>" +
      '<td class="mono' + (o.strategy ? '">' + o.strategy : ' dim">기록없음') + "</td>" +
      '<td class="mono">' + o.orderedQty + " / " + o.filledQty + "</td></tr>";
  });
  html += "</tbody></table></div>";
  return html;
}
