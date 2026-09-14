/* Overview 탭 - 계좌 상태를 5~10초 안에 파악하는 첫 화면(2026-09-14 전면 개편,
   같은 날 계좌 전환 서브탭 추가). 1차 KIS 국내주식 Paper Trading/VTS를
   기본으로 하되, 업비트·빗썸 실계좌·RV20 선물(다른 브로커, System 탭에
   있던 것)을 서브탭으로 옮겨와 한 곳에서 오갈 수 있게 한다 - Overview
   총자산·KPI에는 여전히 안 섞는다(모의투자 vs 실제 돈은 절대 같은 숫자로
   안 더한다). */
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
    const rv20 = await PT.tryFetchJson("data/rv20-futures-automation.json");
    let real = null;
    try {
      const r = await fetch("https://wonithink-stock.duckdns.org/accounts?t=" + Date.now());
      if (r.ok) real = (await r.json()).real;
    } catch (e) { /* 서브탭에서 카드만 생략 */ }

    const subtabs = [
      { id: "paper", label: "모의투자" },
      { id: "upbit", label: "업비트 실계좌" },
      { id: "bithumb", label: "빗썸 실계좌" },
      { id: "rv20", label: "RV20 선물" },
    ];
    container.innerHTML =
      '<div class="v-chip-row" id="ov-subtab-nav" style="margin-bottom:12px">' +
      subtabs.map((s, i) => '<button class="v-chip' + (i === 0 ? " active" : "") + '" data-subtab="' + s.id + '">' + s.label + "</button>").join("") +
      "</div>" +
      '<div id="ov-subtab-content"></div>';

    const content = document.getElementById("ov-subtab-content");
    const renderers = {
      paper: () => renderPaperSubtab(content, data, equity, macro),
      upbit: () => renderRealAccountSubtab(content, "업비트", real && real.upbit),
      bithumb: () => renderRealAccountSubtab(content, "빗썸", real && real.bithumb),
      rv20: () => renderRv20Subtab(content, rv20),
    };
    document.querySelectorAll("#ov-subtab-nav .v-chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("#ov-subtab-nav .v-chip").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        renderers[btn.dataset.subtab]();
      });
    });
    renderers.paper();
  },
};

function renderPaperSubtab(container, data, equity, macro) {
  const { account, strategies, trades } = data;
  const strategyEntries = Object.entries(strategies || {});
  const eqHistory = (equity && equity.history) || [];

  container.innerHTML =
    '<div class="panel" style="border-color:var(--warn);margin-bottom:12px">' +
    '<strong style="color:var(--warn)">⚠ 모의투자(가상자금)</strong> — 이 화면의 숫자는 ' +
    "실제 돈이 아닙니다. KIS 모의계좌(VTS)에 실제로 자동 주문이 나가지만 가상자금 기준이고, " +
    "실전 계좌와 체결 방식·수수료가 다를 수 있습니다.</div>" +
    kpiGridHtml(account, eqHistory) +
    '<div class="grid grid-2">' +
      equityChartCardHtml() +
      strategyStatusCardHtml(strategyEntries, account) +
    "</div>" +
    '<div class="grid grid-2">' +
      positionsSummaryCardHtml(strategyEntries) +
      recentActivityCardHtml(trades) +
    "</div>";

  wireEquityChart(eqHistory, macro);
}

// 업비트·빗썸은 실계좌(진짜 자산) - 모의투자와 반대되는 경고를 준다.
// evalKrw가 null인(시세 조회 실패) 보유는 합계에서 빠진 이유를 그대로 보여준다.
function renderRealAccountSubtab(container, label, acctData) {
  const PT = window.PT;
  const won = (v) => v === null || v === undefined ? "—" : PT.formatAccount(v) + "원";

  let html = '<div class="panel" style="border-color:var(--good);margin-bottom:12px">' +
    '<strong style="color:var(--good)">● 실계좌</strong> — ' + label + "는 실제 자산입니다(모의투자 아님). " +
    "15분 간격으로 VM이 직접 조회해 갱신합니다.</div>";

  if (!acctData) {
    html += '<div class="panel"><div class="empty">데이터 없음 — VM의 실계좌 조회 타이머가 아직 안 돌았거나 응답이 없습니다.</div></div>';
    container.innerHTML = html;
    return;
  }

  html += '<div class="kpi-grid"><div class="kpi-card"><div class="kpi-label">총 평가금액(원화 환산)</div>' +
    '<div class="kpi-value mono">' + won(acctData.totalKrw) + "</div>" +
    '<div class="kpi-sub">갱신 ' + (acctData.generatedAtKST ? new Date(acctData.generatedAtKST).toLocaleString("ko-KR") : "-") + "</div></div></div>";

  html += '<div class="panel"><h2>보유 자산</h2>';
  const holdings = acctData.holdings || [];
  if (!holdings.length) {
    html += '<div class="empty">보유 자산이 없습니다.</div>';
  } else {
    html += '<table><thead><tr><th>통화</th><th>보유수량</th><th>평가금액(원)</th></tr></thead><tbody>';
    holdings.forEach((h) => {
      html += "<tr><td style='text-align:left'>" + h.currency + "</td>" +
        '<td class="mono">' + h.balance + "</td>" +
        '<td class="mono' + (h.evalKrw === null ? ' warn">시세 조회 실패' : '">' + PT.formatAccount(h.evalKrw) + "원") + "</td></tr>";
    });
    html += "</tbody></table>";
  }
  if ((acctData.unresolvedCurrencies || []).length) {
    html += '<div class="warn" style="font-size:11px;margin-top:8px">시세 조회 실패로 합계 제외: ' + acctData.unresolvedCurrencies.join(", ") + "</div>";
  }
  html += "</div>";
  container.innerHTML = html;
}

function renderRv20Subtab(container, rv20) {
  const on = !!(rv20 && rv20.enabled);
  const changedAt = rv20 && rv20.lastChangedAt ? new Date(rv20.lastChangedAt).toLocaleString("ko-KR") : "-";
  let html = '<div class="panel" style="border-color:var(--warn);margin-bottom:12px">' +
    '<strong style="color:var(--warn)">⚠ 이것도 모의투자입니다</strong> — RV20 선물은 KIS 국내선물 ' +
    "모의계좌(VTS)에 실제 자동 주문이 나가는 별도 전략입니다. 국내주식 모의투자와 같은 계좌가 아니라 자산이 안 섞이고, " +
    "실제 돈도 아닙니다.</div>";
  html += '<div class="panel"><h2>RV20 선물 sizing 자동실행</h2>';
  html += '<div class="sys-source-row"><span class="sys-source-name">상태</span>' +
    '<span class="pill ' + (on ? "pill-good" : "pill-dim") + '"><span class="pill-dot"></span>' + (on ? "켜짐" : "꺼짐") + "</span></div>";
  html += '<div class="dim" style="font-size:11.5px;margin-top:8px">마지막 변경: ' + changedAt +
    (rv20 && rv20.lastChangedBy ? " (" + rv20.lastChangedBy + ")" : "") +
    '<br>켜고 끄려면 GitHub Actions의 "RV20 futures automation on/off switch" 워크플로를 수동 실행합니다.</div>';
  html += '<div class="dim" style="font-size:11.5px;margin-top:8px">계약수·평가손익 등 계좌 상세는 이 정적 사이트에 발행되지 않습니다(VM 로컬에만 있음) — on/off 상태만 확인 가능합니다.</div>';
  html += "</div>";
  container.innerHTML = html;
}

function kpiGridHtml(account, eqHistory) {
  const PT = window.PT;
  const won = (v) => v === null || v === undefined ? "—" : PT.formatAccount(v) + "원";
  const total = account ? account.totalValueKrw : null;

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
    card("총자산", won(total), "") +
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
