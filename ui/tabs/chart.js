// macro.json 의 krKospi·krKosdaq 는 **전 거래일 종가를 오늘 날짜로** 찍는다.
// 실측 2026-09-11: docs/data/history(날짜 라벨이 KIS 일봉과 일치함을 확인)와
// 겹치는 41일 중 39일이 정확히 한 행 밀림 · 같은 날 일치 0건.
//
// 안 고치면 두 군데가 조용히 틀린다 - 벤치마크 비교가 하루 어긋나고,
// Beta 가 하루 밀린 두 계열의 상관으로 계산돼 전부 0 근처로 나온다
// (표의 -0.04 · 0.01 · -0.06 이 그것이다 - 한국 주식 베타가 0 일 리 없다).
//
// ★ 뿌리는 여기가 아니라 macro_layer_daily_kr.parquet 생산자다. 여기 보정은
// 소비 시점 응급처치이고, 생산자를 고치면 이 함수는 지워야 한다.
function realignMacroHistory(history) {
  if (!history || history.length < 2) return history || [];
  const out = [];
  for (let i = 1; i < history.length; i++) {
    out.push({ date: history[i - 1].date, value: history[i].value });
  }
  return out;
}

window.TABS = window.TABS || {};
window.TABS.chart = {
  title: "차트",
  render: async function (container) {
    try {
      // 경로는 문서 기준 상대경로다. "../data/..." 는 로컬(문서가 서버 루트)에서만
      // 우연히 동작했다 - 배포본은 /stock/paper-trading/ 이라 "../" 가 /stock/data/
      // 로 빠져나가 404 였다(2026-09-03 사용자 보고). 다른 탭과 같은 "data/..." 로 통일.
      const res = await fetch("data/positions.json");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();

      // 벤치마크(KOSPI) - Beta·변동성 계산용, 없어도 포지션 화면 자체는
      // 떠야 하니 fail-soft(못 받으면 그 두 컬럼만 "-"로 표시).
      let kospiHistory = null;
      let kosdaqHistory = null;
      for (const path of ["data/macro.json", "ui/data/macro.json"]) {
        try {
          const mRes = await fetch(path);
          if (!mRes.ok) continue;
          const mData = await mRes.json();
          const series = mData.series || {};
          kospiHistory = realignMacroHistory(series.krKospi && series.krKospi.history);
          kosdaqHistory = realignMacroHistory(series.krKosdaq && series.krKosdaq.history);
          if (kospiHistory) break;
        } catch (e) { /* 다음 경로 시도 */ }
      }

      // 계좌 총평가 이력 - build_ui_feed.py 가 하루 한 줄씩 쌓는다(2026-09-11
      // 신설). 그 전 기간은 없다(소급 불가) - 없으면 벤치마크만 그린다.
      let equityHistory = null;
      try {
        const eRes = await fetch("data/equity-history.json");
        if (eRes.ok) equityHistory = (await eRes.json()).history;
      } catch (e) { /* 벤치마크만 그린다 */ }

      // 종목명 조회 - 없어도(신규 상장 등 매핑 누락) 코드만 보이면 되니 fail-soft.
      let tickerNames = {};
      try {
        const nRes = await fetch("data/ticker-names.json");
        if (nRes.ok) tickerNames = await nRes.json();
      } catch (e) { /* 코드만 표시 */ }

      renderChartTab(container, data, kospiHistory, tickerNames, kosdaqHistory, equityHistory);
    } catch (e) {
      const msg = String((e && e.message) || e);
      // positions.json 은 KIS 모의계좌를 읽는 로컬 스크립트(build_ui_feed.py)가
      // 만들고 .gitignore 대상이라 배포본에는 없을 수 있다. 그때 HTTP 404 원문만
      // 띄우면 "화면이 깨졌다"로 읽힌다 - 무엇이 없는지 그대로 말한다(절대 규칙 1).
      container.innerHTML = /404/.test(msg)
        ? '<div class="empty">페이퍼 트레이딩 포지션 데이터(<code>data/positions.json</code>)가 이 배포본에 없습니다.<br>' +
          'KIS 모의계좌를 조회하는 <code>research/strategy-lab/build_ui_feed.py</code> 가 로컬에서 만드는 파일이고, ' +
          '아직 이걸 발행하는 워크플로가 없습니다.<br><span class="dim">다른 탭(스코어링·리서치랩·매크로·데이터 상태)은 정상 동작합니다.</span></div>'
        : '<div class="empty">데이터 로드 실패: ' + msg + "</div>";
    }
  }
};

function renderChartTab(container, data, kospiHistory, tickerNames, kosdaqHistory, equityHistory) {
  const { updatedAt, historyAsOf, account, strategies, trades } = data;
  const strategyEntries = Object.entries(strategies);
  const totalPositions = strategyEntries.reduce((n, [, s]) => n + (s.positions || []).length, 0);
  const openCount = strategyEntries.reduce((n, [, s]) =>
    n + (s.positions || []).filter((p) => p.status === "OPEN").length, 0);

  let html = "";

  // VM(stock-new)의 paper-trading-poll.timer가 장중 10분 간격으로 KIS
  // 모의투자 계좌에 실제 주문을 낸다(Paper Trading Engine 5단계, 2026-09-04
  // 착수). "라이브"이되 가상자금·모의계좌라 실제 손익이 아니다 - 둘 다
  // 지어내지 않고 그대로 말한다(절대 규칙 1).
  html += '<div class="panel" style="border-color:var(--warn);margin-bottom:12px;">' +
    '<strong style="color:var(--warn)">⚠ 모의투자 파일럿</strong> — KIS 모의계좌(가상자금)에 ' +
    '실제로 자동 주문이 나갑니다. 실제 돈이 아니고, 월별 리밸런싱일(<span class="mono">' +
    (Object.values(strategies)[0]?.positions?.[0]?.intentDate || "-") +
    '</span> 등)마다 새로 선정된 종목만 진입합니다 - 체결은 며칠에 걸쳐 반영될 수 있습니다.</div>';

  // 계좌 요약 - 히어로 스탯 바 (전문 트레이딩 터미널의 상단 계좌 바 참고)
  html += '<div class="panel account-hero">';
  // 예수금은 둘이다 - 한국 주식은 D+2 결제라 어제 산 값이 아직 안 빠진
  // 잔고(dnca)와 실제로 쓸 수 있는 돈(D+2)이 다르다. 하나만 보이면 도넛의
  // 예수금과 어긋나 보인다(실측 2026-09-11: 150,278,637 vs 100,596,273,
  // 차이 49,682,364 = 어제 매수대금 + 제비용).
  const settling = (account?.settlingKrw || 0) + (account?.settlingFeeKrw || 0);
  html += '  <div class="hero-stat"><div class="stat-label">예수금</div><div class="stat-value-lg mono">' +
    formatAccount(account?.cashKrw) + "</div>" +
    (account?.cashAvailableKrw != null
      ? '<div class="dim mono" style="font-size:11px">가용(D+2) ' + formatAccount(account.cashAvailableKrw) +
        (settling ? " · 결제대기 " + formatAccount(settling) : "") + "</div>"
      : "") + "</div>";
  html += '  <div class="hero-stat"><div class="stat-label">평가금액</div><div class="stat-value-lg mono">' +
    formatAccount(account?.totalValueKrw) + "</div>" +
    (account?.stockValueKrw != null
      ? '<div class="dim mono" style="font-size:11px">주식 ' + formatAccount(account.stockValueKrw) + "</div>"
      : "") + "</div>";
  html += '  <div class="hero-stat"><div class="stat-label">보유/전체 포지션</div><div class="stat-value-lg mono">' + openCount + " / " + totalPositions + "</div></div>";
  html += '  <div class="hero-stat"><div class="stat-label">기준일</div><div class="stat-value-lg mono" style="font-size:18px">' + (historyAsOf || "-") + "</div></div>";
  html += '  <div class="dim mono account-hero-updated">최종 갱신 ' + (updatedAt || "-") + "</div>";
  html += "</div>";

  const allPositions = [];
  strategyEntries.forEach(([strategyId, strategy]) => {
    (strategy.positions || []).forEach((pos) => {
      allPositions.push({ ...pos, strategyId });
    });
  });

  // 자산 구성 - 종목 유니버스가 latest.json(운영 스코어링) 대상과 겹치지
  // 않아(교차 확인함) 섹터별이 아니라 전략별로 구성한다. 지금은 포지션
  // 전량이 PENDING_ENTRY라 "이미 투자된 비중"이 아니라 "체결되면"의
  // 추정치임을 라벨로 명시한다 - 실제로 안 산 걸 산 것처럼 보이면 안 된다.
  html += '<div class="panel">';
  html += '  <h2>자산 배분 — 전략별' +
    (openCount === totalPositions ? " 보유 평가액" : " (일부 미체결 — 체결되면의 추정 포함)") + "</h2>";
  html += compositionBarsHtml(strategyEntries, account);
  html += "</div>";

  html += benchmarkPanelHtml(kospiHistory, kosdaqHistory, equityHistory);
  html += tradesPanelHtml(trades);

  let selectedSymbol = null;
  let selectedPosition = null;
  let lastDraw = null;

  // canvas 2D는 var()를 못 읽는다 - 그릴 때마다 실제 계산된 색으로 조회.
  function cssVar(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  document.addEventListener("themechange", () => {
    if (lastDraw) drawChart(lastDraw.history, lastDraw.currentPrice, lastDraw.avgEntryPrice);
  });

  function buildTables() {
    let tablesHtml = "";
    strategyEntries.forEach(([strategyId, strategy]) => {
      const positions = strategy.positions || [];
      if (positions.length === 0) return;

      const totals = strategyTotals(positions);
      tablesHtml += '<div class="panel" style="margin-top:12px;">';
      tablesHtml += '  <h2>' + strategyId + ' (' + positions.length + "건)</h2>";
      tablesHtml += '  <div class="strategy-totals mono">' +
        '<span>매수금액 <b>' + formatAccount(totals.cost) + "</b></span>" +
        '<span>평가금액 <b>' + formatAccount(totals.value) + "</b></span>" +
        '<span>평가손익 <b class="' + getPnlClass(totals.cost ? totals.pnl : null) + '">' +
          (totals.cost ? formatPnl(totals.pnl) + " (" + formatPnlPct(totals.pnlPct) + ")" : "-") +
        "</b></span>" +
        (totals.priced < positions.length
          ? '<span class="dim">' + (positions.length - totals.priced) + "건은 평단가 없음(미체결)</span>"
          : "") +
        "</div>";
      tablesHtml += '  <table>';
      tablesHtml += "    <thead><tr>";
      tablesHtml += '      <th>종목</th><th>추이</th><th>Beta</th><th>변동성(연)</th><th>상태</th><th>수량</th><th>평단가</th><th>매수금액</th><th>현재가</th><th>평가금액</th><th>미실현손익(원)</th><th>미실현손익(%)</th><th>액션</th>';
      tablesHtml += "    </tr></thead><tbody>";

      positions.forEach((pos) => {
        const isSelected = pos.symbol === selectedSymbol;
        const rowClass = isSelected ? ' style="background:var(--row-selected);"' : "";
        tablesHtml += "<tr" + rowClass + ' data-symbol="' + pos.symbol + '">';
        const risk = computeRiskMetrics(pos.history, kospiHistory);
        const tickerName = tickerNames && tickerNames[pos.symbol];
        tablesHtml += '      <td style="text-align:left;">' +
          (tickerName ? tickerName + ' <span class="mono dim" style="font-size:11px">' + pos.symbol + "</span>" : '<span class="mono">' + pos.symbol + "</span>") +
          "</td>";
        tablesHtml += '      <td>' + sparklineSvg(pos.history) + "</td>";
        tablesHtml += '      <td class="mono">' + (risk && risk.beta != null ? risk.beta.toFixed(2) : "-") + "</td>";
        tablesHtml += '      <td class="mono">' + (risk ? risk.volAnnualPct.toFixed(1) + "%" : "-") + "</td>";
        tablesHtml += '      <td><span class="badge ' + getStatusBadgeClass(pos.status) + '">' + pos.status + "</span></td>";
        tablesHtml += '      <td class="mono">' + (pos.quantity ?? "-") + "</td>";
        tablesHtml += '      <td class="mono">' + formatPrice(pos.avgEntryPrice) + "</td>";
        tablesHtml += '      <td class="mono">' +
          (pos.avgEntryPrice ? formatAccount(pos.avgEntryPrice * (pos.quantity || 0)) : "-") + "</td>";
        tablesHtml += '      <td class="mono">' + formatPrice(pos.currentPrice) + "</td>";
        tablesHtml += '      <td class="mono">' +
          (pos.currentPrice ? formatAccount(pos.currentPrice * (pos.quantity || 0)) : "-") + "</td>";
        tablesHtml += '      <td class="mono ' + getPnlClass(pos.unrealizedPnlKrw) + '">' + formatPnl(pos.unrealizedPnlKrw) + "</td>";
        tablesHtml += '      <td class="mono ' + getPnlClass(pos.unrealizedPnlPct) + '">' + formatPnlPct(pos.unrealizedPnlPct) + "</td>";
        tablesHtml += '      <td>';
        if (pos.status === "PENDING_ENTRY" || pos.status === "ENTRY_SUBMITTED") {
          tablesHtml += '        <button class="btn buy" data-symbol="' + pos.symbol + '" data-side="BUY" data-qty="' + (pos.quantity || 1) + '">매수</button>';
          tablesHtml += '        <button class="btn sell" data-symbol="' + pos.symbol + '" data-side="SELL" data-qty="' + (pos.quantity || 1) + '">매도</button>';
        } else if (pos.status === "OPEN") {
          tablesHtml += '        <button class="btn sell" data-symbol="' + pos.symbol + '" data-side="SELL" data-qty="' + (pos.quantity || 1) + '">매도</button>';
        } else {
          tablesHtml += '        <span class="dim">-</span>';
        }
        tablesHtml += "      </td>";
        tablesHtml += "    </tr>";
      });

      tablesHtml += "  </tbody></table>";
      tablesHtml += "</div>";
    });
    return tablesHtml;
  }

  // 차트를 계좌 요약 바로 다음, 테이블보다 위에 - 트레이딩 터미널은 차트가
  // 주인공이지 스크롤해서 찾는 부가 정보가 아니다.
  html += '<div class="panel chart-panel">';
  html += '  <div class="chart-panel-head"><h2 style="margin:0">가격 차트</h2><span id="chart-title" class="mono chart-symbol-title"></span></div>';
  html += '  <div class="chart-canvas-wrap"><canvas id="price-chart"></canvas>';
  html += '  <div id="chart-tooltip" class="chart-tooltip"></div></div>';
  html += "</div>";

  html += '<div id="tables-container">' + buildTables() + "</div>";

  container.innerHTML = html;

  const tooltip = document.getElementById("chart-tooltip");
  const chartCanvas = document.getElementById("price-chart");
  const chartTitle = document.getElementById("chart-title");
  const tablesContainer = document.getElementById("tables-container");

  function attachRowListeners() {
    tablesContainer.querySelectorAll("tbody tr").forEach((row) => {
      row.addEventListener("click", () => {
        tablesContainer.querySelectorAll("tbody tr").forEach((r) => (r.style.background = ""));
        row.style.background = "var(--row-selected)";
        selectedSymbol = row.dataset.symbol;
        selectedPosition = allPositions.find((p) => p.symbol === selectedSymbol);
        if (selectedPosition) {
          drawChart(selectedPosition.history, selectedPosition.currentPrice, selectedPosition.avgEntryPrice);
          chartTitle.textContent = selectedSymbol + " (" + selectedPosition.strategyId + ")";
        }
      });
      row.addEventListener("mouseenter", () => {
        if (row.dataset.symbol !== selectedSymbol) row.style.background = "var(--row-hover)";
      });
      row.addEventListener("mouseleave", () => {
        if (row.dataset.symbol !== selectedSymbol) row.style.background = "";
      });
    });

    tablesContainer.querySelectorAll(".btn.buy, .btn.sell").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const symbol = btn.dataset.symbol;
        const side = btn.dataset.side;
        const quantity = parseInt(btn.dataset.qty, 10);
        placeOrder(symbol, side, quantity);
      });
    });
  }

  attachRowListeners();

  if (allPositions.length > 0) {
    const first = allPositions[0];
    selectedSymbol = first.symbol;
    selectedPosition = first;
    tablesContainer.querySelector('tr[data-symbol="' + first.symbol + '"]').style.background = "var(--row-selected)";
    drawChart(first.history, first.currentPrice, first.avgEntryPrice);
    chartTitle.textContent = first.symbol + " (" + first.strategyId + ")";
  }

  function drawChart(history, currentPrice, avgEntryPrice) {
    lastDraw = { history, currentPrice, avgEntryPrice };
    if (!history || history.length === 0) {
      const ctx = chartCanvas.getContext("2d");
      ctx.clearRect(0, 0, chartCanvas.width, chartCanvas.height);
      ctx.fillStyle = cssVar("--text-dim");
      ctx.font = "14px var(--mono)";
      ctx.textAlign = "center";
      ctx.fillText("차트 데이터 없음", chartCanvas.width / 2, chartCanvas.height / 2);
      return;
    }

    const ctx = chartCanvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const rect = chartCanvas.getBoundingClientRect();
    chartCanvas.width = Math.round(rect.width * dpr);
    chartCanvas.height = Math.round(rect.height * dpr);
    ctx.scale(dpr, dpr);
    const width = rect.width;
    const height = rect.height;

    const prices = history.map((h) => h.close);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const priceRange = maxPrice - minPrice || 1;
    const padding = { top: 20, right: 60, bottom: 30, left: 60 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;

    const xScale = (i) => padding.left + (i / (history.length - 1)) * plotWidth;
    const yScale = (price) => padding.top + (1 - (price - minPrice) / priceRange) * plotHeight;

    ctx.clearRect(0, 0, width, height);

    ctx.strokeStyle = cssVar("--panel-border");
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
      const y = padding.top + (i / 4) * plotHeight;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
    }
    for (let i = 0; i <= 5; i++) {
      const x = padding.left + (i / 5) * plotWidth;
      ctx.beginPath();
      ctx.moveTo(x, padding.top);
      ctx.lineTo(x, height - padding.bottom);
      ctx.stroke();
    }

    if (currentPrice) {
      const y = yScale(currentPrice);
      ctx.strokeStyle = cssVar("--accent");
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = cssVar("--accent");
      ctx.font = "11px var(--mono)";
      ctx.textAlign = "right";
      ctx.fillText(formatPriceShort(currentPrice) + " (현재가)", width - padding.right + 5, y + 4);
    }

    if (avgEntryPrice && avgEntryPrice >= minPrice && avgEntryPrice <= maxPrice) {
      const y = yScale(avgEntryPrice);
      ctx.strokeStyle = cssVar("--warn");
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 6]);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = cssVar("--warn");
      ctx.font = "11px var(--mono)";
      ctx.textAlign = "right";
      ctx.fillText(formatPriceShort(avgEntryPrice) + " (평단가)", width - padding.right + 5, y - 8);
    }

    ctx.strokeStyle = cssVar("--accent");
    ctx.lineWidth = 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    history.forEach((h, i) => {
      const x = xScale(i);
      const y = yScale(h.close);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    const lastIdx = history.length - 1;
    const lastX = xScale(lastIdx);
    const lastY = yScale(history[lastIdx].close);
    ctx.fillStyle = cssVar("--accent");
    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = cssVar("--bg");
    ctx.lineWidth = 2;
    ctx.stroke();

    chartCanvas.onmousemove = (e) => {
      const rect = chartCanvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      if (mouseX < padding.left || mouseX > width - padding.right) {
        tooltip.style.display = "none";
        return;
      }
      const idx = Math.round(((mouseX - padding.left) / plotWidth) * (history.length - 1));
      const clampedIdx = Math.max(0, Math.min(history.length - 1, idx));
      const point = history[clampedIdx];
      const x = xScale(clampedIdx);
      const y = yScale(point.close);

      tooltip.style.display = "block";
      // 툴팁은 .chart-canvas-wrap(position:relative) 기준 절대좌표 -
      // canvas와 wrap이 같은 크기라 캔버스 로컬 좌표(x,y)를 그대로 쓴다.
      tooltip.style.left = x + 12 + "px";
      tooltip.style.top = Math.max(0, y - 28) + "px";
      tooltip.textContent = point.date + " | " + formatPrice(point.close);

      ctx.clearRect(0, 0, width, height);
      drawChart(history, currentPrice, avgEntryPrice);
      ctx.fillStyle = cssVar("--accent");
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = cssVar("--bg");
      ctx.lineWidth = 2;
      ctx.stroke();
    };
    chartCanvas.onmouseleave = () => {
      tooltip.style.display = "none";
      drawChart(history, currentPrice, avgEntryPrice);
    };
  }

  function placeOrder(symbol, side, quantity) {
    const now = new Date();
    const timestamp = now.toISOString().replace(/[-:]/g, "").replace(/\..+/, "");
    const filename = timestamp + "_" + symbol + "_" + side + ".json";
    const order = {
      symbol,
      side,
      quantity,
      reason: "chart_trader_manual",
      requestedAt: now.toISOString()
    };

    const pendingKey = "pending_orders";
    let pending = JSON.parse(localStorage.getItem(pendingKey) || "[]");
    pending.push({ filename, order, savedAt: now.toISOString() });
    localStorage.setItem(pendingKey, JSON.stringify(pending));

    const blob = new Blob([JSON.stringify(order, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    alert("주문 요청 접수됨: " + filename + "\n(파일이 다운로드되었고 localStorage에도 저장됨)");
  }

  // Beta·연환산 변동성 - 종목 종가와 KOSPI를 날짜로 맞춘 뒤 일별 수익률로
  // 계산한다(공분산/KOSPI분산, 표준편차*sqrt(252)). 외부 API 불필요 - 이미
  // 있는 가격 데이터로 충분하다. 겹치는 거래일이 20일 미만이면 노이즈만
  // 큰 숫자를 보여주는 셈이라 아예 "-"로 유보한다(이 프로젝트의 "정직한
  // 점수" 원칙과 동일하게 UI 쪽에도 적용).
  function computeRiskMetrics(history, kospiHist) {
    if (!history || !kospiHist) return null;
    const kospiMap = new Map(kospiHist.map((h) => [h.date, h.value]));
    const aligned = history.filter((h) => kospiMap.has(h.date));
    if (aligned.length < 21) return null;

    const stockRet = [];
    const kospiRet = [];
    for (let i = 1; i < aligned.length; i++) {
      const prevKospi = kospiMap.get(aligned[i - 1].date);
      const curKospi = kospiMap.get(aligned[i].date);
      stockRet.push(aligned[i].close / aligned[i - 1].close - 1);
      kospiRet.push(curKospi / prevKospi - 1);
    }
    const n = stockRet.length;
    const mean = (arr) => arr.reduce((a, b) => a + b, 0) / arr.length;
    const meanS = mean(stockRet), meanK = mean(kospiRet);
    let cov = 0, varK = 0, varS = 0;
    for (let i = 0; i < n; i++) {
      const ds = stockRet[i] - meanS, dk = kospiRet[i] - meanK;
      cov += ds * dk; varK += dk * dk; varS += ds * ds;
    }
    cov /= n; varK /= n; varS /= n;
    return {
      beta: varK > 0 ? cov / varK : null,
      volAnnualPct: Math.sqrt(varS) * Math.sqrt(252) * 100,
      n
    };
  }

  // SVG는 실제 DOM이라(캔버스와 달리) style="stroke:var(...)"가 테마 전환에
  // 그냥 반응한다 - cssVar() 조회나 themechange 리스너가 따로 필요 없다.
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

  // 포트폴리오가 **아직 사는 중**이던 구간은 지수와 직접 비교할 수 없다.
  // 현금이 대부분이면 지수가 올라도 계좌는 안 오른다 - 그건 성과가 아니라
  // 현금 비중의 산수다. 실측 2026-09-04: 투자비중 2.1% 로 시작해 09-10 에
  // 80% 가 됐고, 그 구간만 보면 계좌 +0.28% vs 코스피 +7.18% 로 보인다.
  // 안 밝히면 "내 전략이 5% 뒤진다"로 읽히는데 사실이 아니다.
  function rampNoteHtml(equity, series, start) {
    const rows = (equity || []).filter((r) => r.date >= start && r.totalKrw && r.stockKrw != null);
    if (rows.length < 2) return "";
    const ratio = (r) => (r.stockKrw / r.totalKrw) * 100;
    const lo = Math.min(...rows.map(ratio)), hi = Math.max(...rows.map(ratio));
    if (hi - lo < 5) return "";            // 비중이 안정적이면 할 말이 없다

    // 램프 끝 = 비중이 마지막으로 2%p 넘게 오른 날(= 마지막 매수일)
    let rampEnd = rows[0].date;
    for (let i = 1; i < rows.length; i++) {
      if (ratio(rows[i]) - ratio(rows[i - 1]) > 2) rampEnd = rows[i].date;
    }
    let out = '<div class="warn" style="font-size:11px;margin-top:8px">' +
      "⚠ " + start + " ~ " + rampEnd + " 는 <b>아직 매수 중이던 구간</b>입니다 (투자비중 " +
      lo.toFixed(1) + "% → " + hi.toFixed(1) + "%). 현금이 대부분이면 지수가 올라도 계좌는 안 오릅니다 — " +
      "이 구간의 격차는 성과가 아니라 현금 비중입니다.</div>";

    // 램프 이후만 다시 비교한다 - 이게 실제로 견줄 수 있는 구간이다.
    const after = series.map((s) => {
      const r = s.rows.filter((x) => x.date >= rampEnd && x.v);
      return r.length >= 2 ? { label: s.label, color: s.color, pct: (r[r.length - 1].v / r[0].v - 1) * 100 } : null;
    }).filter(Boolean);
    if (after.length) {
      out += '<div style="font-size:12px;margin-top:6px">전액 투자 이후(' + rampEnd + " 기준): " +
        after.map((a) => '<span style="margin-right:14px"><span class="legend-dot" style="display:inline-block;background:' +
          a.color + '"></span> ' + a.label + ' <span class="mono ' + getPnlClass(a.pct) + '">' +
          formatPnlPct(a.pct) + "</span></span>").join("") + "</div>";
    }
    return out;
  }

  // 벤치마크 비교 - 코스피·코스닥·내 계좌를 한 그림에 겹친다.
  //
  // 절대수준이 자릿수가 달라(지수 2,500 vs 계좌 5억) 같은 축에 못 놓는다 -
  // **공통 시작일 = 100** 으로 정규화한다. 시작일은 세 계열이 다 있는 첫 날이고,
  // 계좌 이력이 2026-09-11 부터라 그 전은 지수만 그린다(소급 불가).
  //
  // canvas 대신 SVG 폴리라인이다 - 축 눈금과 툴팁이 필요 없는 비교선이라
  // 가격 차트의 캔버스 기계를 다시 쓸 이유가 없다.
  function benchmarkPanelHtml(kospi, kosdaq, equity) {
    const series = [
      { key: "kospi", label: "코스피", color: "var(--accent)",
        rows: (kospi || []).map((h) => ({ date: h.date, v: h.value })) },
      { key: "kosdaq", label: "코스닥", color: "var(--warn)",
        rows: (kosdaq || []).map((h) => ({ date: h.date, v: h.value })) },
      { key: "acct", label: "내 계좌", color: "var(--good)",
        rows: (equity || []).map((h) => ({ date: h.date, v: h.totalKrw })) },
    ].filter((s) => s.rows.length >= 2);

    let out = '<div class="panel" style="margin-top:12px;"><h2>벤치마크 비교 — 코스피 · 코스닥 · 내 계좌</h2>';
    if (!series.length) return out + '<div class="empty">비교할 계열이 없습니다.</div></div>';

    // 계좌가 있으면 그 시작일부터 - 비교는 셋이 다 있는 구간에서만 뜻이 있다.
    const acct = series.find((s) => s.key === "acct");
    const start = acct ? acct.rows[0].date : series[0].rows[0].date;
    const norm = series.map((s) => {
      const rows = s.rows.filter((r) => r.date >= start && r.v);
      const base = rows.length ? rows[0].v : null;
      return { ...s, pts: base ? rows.map((r) => ({ date: r.date, y: (r.v / base) * 100 })) : [] };
    }).filter((s) => s.pts.length >= 2);

    if (!norm.length) {
      return out + '<div class="empty">계좌 이력이 아직 2일치가 안 됩니다 — ' +
        '<code>build_ui_feed.py</code> 가 오늘부터 하루 한 줄씩 쌓습니다(소급 불가).</div></div>';
    }

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

    // 범례는 "같은 자리에서 출발해 지금 몇 퍼센트" 를 그대로 읽게 쓴다 -
    // 정규화 값(100 기준)이 아니라 **각 계열의 실제 수준**을 같이 보인다.
    // 지수 6,562 -> 7,033 와 계좌 5억 -> 5.01억이 같은 줄에서 비교된다.
    const legend = norm.map((s) => {
      const raw = s.rows.filter((r) => r.date >= start && r.v);
      const a = raw[0].v, b = raw[raw.length - 1].v;
      const pct = (b / a - 1) * 100;
      const fmt = (v) => (v >= 1e8 ? (v / 1e8).toFixed(2) + "억" : formatPriceShort(Math.round(v * 100) / 100));
      return '<tr><td><span class="legend-dot" style="display:inline-block;background:' + s.color +
        '"></span> ' + s.label + '</td>' +
        '<td class="mono dim">' + fmt(a) + "</td><td class='dim'>→</td>" +
        '<td class="mono">' + fmt(b) + "</td>" +
        '<td class="mono ' + getPnlClass(pct) + '" style="font-weight:700">' + formatPnlPct(pct) + "</td></tr>";
    }).join("");

    out += '<div class="dim mono" style="font-size:11px;margin-bottom:4px">기준일 ' + start +
           " (세 계열 모두 이 날 = 같은 출발점) · " + dates.length + "일</div>";
    out += svg + '<table class="bench-legend" style="font-size:12px;margin-top:6px;width:auto">' +
           legend + "</table>";
    out += rampNoteHtml(equity, series, start);
    if (!acct) {
      out += '<div class="dim" style="font-size:11px;margin-top:6px">계좌 곡선은 이력이 쌓이는 대로 붙습니다 — ' +
             '총평가액을 하루 한 줄로 적기 시작한 게 2026-09-11 이고, 그 전은 기록이 없어 소급되지 않습니다.</div>';
    }
    return out + "</div>";
  }

  // 매매(리밸런싱) 내역 - 금액·체결가는 KIS 일별주문체결 조회가 정본이고,
  // 전략 귀속은 엔진이 주문을 낼 때 남긴 주문번호->전략 원장으로 붙인다
  // (positionStore.record_order). 계좌 응답 자체에는 전략이 없다.
  //
  // 원장에 없는 주문(원장 도입 이전)은 날짜별 잔차로 "기록없음" 행이 된다 -
  // 뺄셈이라 짐작이 아니다. 종목·수량으로 되짚어 어느 전략에 밀어 넣지
  // 않는다(같은 종목을 여러 전략이 겹쳐 들어서 그건 짐작이 된다, 절대 규칙 1).
  function tradesPanelHtml(trades) {
    if (!trades) return "";
    let out = '<div class="panel" style="margin-top:12px;">';
    out += '  <h2>매매 내역 — 리밸런싱 (' + (trades.fromDate || "?") + " ~ " + (trades.toDate || "?") + ")</h2>";

    if (trades.error) {
      out += '<div class="empty">체결내역을 못 읽었습니다: ' + trades.error +
             '<br><span class="dim">없는 것이 아니라 못 본 것입니다 - 금액을 0으로 표시하지 않습니다.</span></div>';
      return out + "</div>";
    }

    const pending = trades.pending || [];
    if (pending.length) {
      out += '<h3 style="margin:4px 0 6px">진행 중인 주문 ' + pending.length + '건 <span class="dim" style="font-weight:400;font-size:11px">— 오늘 주문만(KRX 주문은 당일 유효)</span></h3>';
      out += '<table><thead><tr><th>주문일</th><th>전략</th><th>종목</th><th>구분</th><th>주문</th><th>체결</th><th>미체결</th></tr></thead><tbody>';
      pending.forEach((o) => {
        out += "<tr>" +
          '<td class="mono">' + o.date + "</td>" +
          '<td class="mono' + (o.strategy ? '">' + o.strategy : ' dim">기록없음') + "</td>" +
          '<td style="text-align:left">' + (o.name || "") + ' <span class="mono dim" style="font-size:11px">' + o.symbol + "</span></td>" +
          '<td><span class="badge ' + (o.side === "SELL" ? "status-submitted" : "status-pending") + '">' +
            (o.side === "SELL" ? "매도" : "매수") + "</span></td>" +
          '<td class="mono">' + o.orderedQty + "</td>" +
          '<td class="mono">' + o.filledQty + "</td>" +
          '<td class="mono warn">' + o.pendingQty + "</td>" +
          "</tr>";
      });
      out += "</tbody></table>";
    } else {
      out += '<div class="dim" style="margin-bottom:8px">진행 중인 주문 없음 — 오늘 낸 주문 중 미체결 잔량이 남은 것이 없습니다.</div>';
    }

    const days = trades.days || [];
    if (!days.length) {
      out += '<div class="empty">이 기간에 체결된 매매가 없습니다.</div>';
      return out + "</div>";
    }
    const sum = days.reduce((a, d) => ({
      buy: a.buy + d.buyKrw, sell: a.sell + d.sellKrw,
      realized: a.realized + (d.realizedKrw || 0), rFrom: a.rFrom + (d.realizedFrom || 0),
    }), { buy: 0, sell: 0, realized: 0, rFrom: 0 });

    // 날짜 -> 전략 -> 그날 합계. 전략 귀속은 주문 원장(주문번호->전략)으로만
    // 하고, 원장에 없는 주문은 날짜별 잔차를 그대로 "기록없음"으로 낸다 -
    // 종목·수량으로 되짚어 어느 전략에 밀어 넣지 않는다(그건 짐작이다).
    const byStrategy = trades.byStrategy || {};
    const perDate = {};
    Object.entries(byStrategy).forEach(([sid, sdays]) => {
      (sdays || []).forEach((d) => { (perDate[d.date] = perDate[d.date] || []).push({ sid, d }); });
    });

    out += '<h3 style="margin:12px 0 6px">날짜별 체결 ' + days.length + "일</h3>";
    out += '<table><thead><tr><th>날짜</th><th>전략</th><th>매수금액</th><th>매수건</th><th>매도금액</th><th>매도건</th><th>순매수</th><th>실현손익</th></tr></thead><tbody>';
    const dayRow = (dateCell, label, labelClass, d) =>
      "<tr>" +
      '<td class="mono">' + dateCell + "</td>" +
      '<td class="mono ' + labelClass + '">' + label + "</td>" +
      '<td class="mono up">' + (d.buyKrw ? formatAccount(d.buyKrw) : "-") + "</td>" +
      '<td class="mono dim">' + (d.buyCount || "-") + "</td>" +
      '<td class="mono down">' + (d.sellKrw ? formatAccount(d.sellKrw) : "-") + "</td>" +
      '<td class="mono dim">' + (d.sellCount || "-") + "</td>" +
      '<td class="mono ' + getPnlClass(d.netKrw) + '">' + formatPnl(d.netKrw) + "</td>" +
      // 잰 건이 0이면 "-" 다. 0원이 아니다 - 원장 이전 매도는 진입가를 모른다.
      '<td class="mono ' + (d.realizedFrom ? getPnlClass(d.realizedKrw) : "dim") + '">' +
        (d.realizedFrom ? formatPnl(d.realizedKrw) +
          (d.realizedFrom < d.sellCount ? ' <span class="dim" style="font-size:10px">' +
            d.realizedFrom + "/" + d.sellCount + "</span>" : "")
         : (d.sellCount ? "기록없음" : "-")) + "</td>" +
      "</tr>";
    days.forEach((d) => {
      const parts = perDate[d.date] || [];
      parts.forEach(({ sid, d: sd }, i) => { out += dayRow(i === 0 ? d.date : "", sid, "", sd); });
      // 잔차 = 계좌 - 귀속된 것. 뺄셈이라 짐작이 아니다.
      const rest = {
        buyKrw: d.buyKrw - parts.reduce((a, p) => a + p.d.buyKrw, 0),
        sellKrw: d.sellKrw - parts.reduce((a, p) => a + p.d.sellKrw, 0),
        buyCount: d.buyCount - parts.reduce((a, p) => a + p.d.buyCount, 0),
        sellCount: d.sellCount - parts.reduce((a, p) => a + p.d.sellCount, 0),
        realizedKrw: 0, realizedFrom: 0,   // 원장에 없는 주문이라 진입가가 없다
      };
      rest.netKrw = rest.buyKrw - rest.sellKrw;
      if (rest.buyKrw || rest.sellKrw) {
        out += dayRow(parts.length ? "" : d.date, "기록없음", "dim", rest);
      }
    });
    out += '</tbody><tfoot><tr><th>합계</th><th class="dim">계좌 전체</th>' +
      '<th class="mono up">' + formatAccount(sum.buy) + "</th><th></th>" +
      '<th class="mono down">' + formatAccount(sum.sell) + "</th><th></th>" +
      '<th class="mono ' + getPnlClass(sum.buy - sum.sell) + '">' + formatPnl(sum.buy - sum.sell) + "</th>" +
      '<th class="mono ' + (sum.rFrom ? getPnlClass(sum.realized) : "dim") + '">' +
        (sum.rFrom ? formatPnl(sum.realized) : "-") + "</th></tr></tfoot>";
    out += "</table>";
    const un = trades.unattributed || {};
    out += '<div class="dim" style="font-size:11px;margin-top:6px">체결분만 셉니다(미체결은 위 표로 갑니다). ' +
           '전략 귀속은 엔진이 주문을 낼 때 남긴 <b>주문번호→전략</b> 원장으로만 합니다 — ' +
           '계좌 응답에는 전략이 없고, 종목·수량으로 되짚는 건 겹쳐 든 종목에서 짐작이 됩니다.' +
           (un.count ? ' <b>기록없음 ' + un.count + '건</b>(매수 ' + formatAccount(un.buyKrw) +
                       ' · 매도 ' + formatAccount(un.sellKrw) + ')은 원장 이전 주문이라 되살릴 수 없습니다.' : "") +
           ' 실현손익 = (체결평균가 − 진입가) × 체결수량, <b>수수료·세금 전</b>입니다 — ' +
           '진입가는 원장에만 있어서(매도가 체결되면 포지션이 삭제됩니다) 원장 이전 매도는 잴 수 없고, ' +
           '0원으로 메우지 않고 "기록없음"으로 둡니다.' +
           ' KIS 일별주문체결 조회는 3개월까지만 줍니다.</div>';
    return out + "</div>";
  }

  // 전략 한 덩어리의 원가·평가·손익. 도넛 범례와 전략별 표 머리가 같은 것을
  // 쓴다 - 두 벌로 계산하면 언젠가 갈리고, 갈린 쪽이 맞는지 화면으로는 못 가린다.
  // 원가는 평단가가 있는 포지션만 센다(PENDING_ENTRY 는 아직 산 게 아니다 -
  // 0 으로 세면 손익률 분모가 부풀어 수익률이 작아 보인다, 교훈57).
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

  function compositionBarsHtml(strategyEntries, account) {
    const total = account?.totalValueKrw;
    if (!total) return '<div class="empty">계좌 정보 없음</div>';
    const palette = ["var(--accent)", "var(--warn)", "var(--good)", "var(--up)"];
    const rows = strategyEntries.map(([strategyId, strategy], i) => {
      const t = strategyTotals(strategy.positions);
      return { label: strategyId, value: t.value, totals: t, color: palette[i % palette.length] };
    });
    const committedTotal = rows.reduce((s, r) => s + r.value, 0);
    // ★ 예수금을 '총평가 - 전략합'으로 유도하지 않는다. 유도하면 전략 장부가
    // 계좌와 어긋나도 예수금이 그 차이를 흡수해 버려 영원히 맞아 보인다
    // (교훈72). 계좌가 말하는 D+2 예수금을 그대로 쓰고, 남는 차이는 아래
    // 한 줄로 드러낸다.
    const cashSlice = account?.cashAvailableKrw != null
      ? account.cashAvailableKrw : Math.max(0, total - committedTotal);
    rows.push({ label: "예수금(D+2 가용)", value: cashSlice, color: "var(--surface-3)" });
    const bookGap = account?.stockValueKrw != null ? committedTotal - account.stockValueKrw : null;

    // conic-gradient 세그먼트 문자열 - 누적 %로 이어붙인다.
    let cursor = 0;
    const segments = rows.map((r) => {
      const pct = total ? (r.value / total) * 100 : 0;
      const from = cursor;
      cursor += pct;
      return r.color + " " + from.toFixed(2) + "% " + cursor.toFixed(2) + "%";
    }).join(", ");

    const legend = rows.map((r) => {
      const pct = total ? (r.value / total) * 100 : 0;
      const t = r.totals;
      const pnlCell = t && t.cost
        ? '<span class="legend-value ' + getPnlClass(t.pnl) + '" style="min-width:150px">' +
            formatPnl(t.pnl) + " (" + formatPnlPct(t.pnlPct) + ")</span>"
        : (t ? '<span class="legend-value dim" style="min-width:150px">미체결</span>' : "");
      const costCell = t
        ? '<span class="legend-value dim" style="min-width:110px">매수 ' + formatAccount(t.cost) + "</span>"
        : "";
      return '<div class="legend-row">' +
        '<span class="legend-dot" style="background:' + r.color + '"></span>' +
        '<span class="legend-label">' + r.label + "</span>" +
        costCell +
        '<span class="legend-value">' + pct.toFixed(1) + "% · " + formatAccount(r.value) + "</span>" +
        pnlCell +
        "</div>";
    }).join("");

    return '<div class="donut-wrap">' +
      '<div class="donut-outer"><div class="donut" style="background:conic-gradient(' + segments + ')"></div>' +
      '<div class="donut-center"><span class="stat-label">총 평가금액</span>' +
      '<span class="mono" style="font-size:15px;font-weight:700">' + formatAccount(total) + "</span></div></div>" +
      '<div class="donut-legend">' + legend +
      '<div class="dim" style="font-size:11px;margin-top:6px">매수 = 체결된 평단가×수량(원가) · 금액 = 현재가 평가액 · 손익 = 미실현(원가 대비). 수수료·세금 전.</div>' +
      (bookGap != null && Math.abs(bookGap) > total * 0.005
        ? '<div class="warn" style="font-size:11px;margin-top:4px">전략 장부 합이 계좌 유가증권평가액과 ' +
          formatPnl(Math.round(bookGap)) + '원 다릅니다 (장부 ' + formatAccount(committedTotal) +
          ' vs 계좌 ' + formatAccount(account.stockValueKrw) + ').</div>'
        : "") +
      "</div></div>";
  }

  function getStatusBadgeClass(status) {
    if (status === "PENDING_ENTRY" || status === "ENTRY_SUBMITTED") return "status-pending";
    if (status === "EXIT_SUBMITTED") return "status-submitted";
    if (status === "OPEN") return "status-open";
    return "";
  }

  function formatPrice(price) {
    if (price === null || price === undefined) return "-";
    return price.toLocaleString("ko-KR", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }

  function formatPriceShort(price) {
    if (price === null || price === undefined) return "-";
    return price.toLocaleString("ko-KR");
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

  function formatAccount(value) {
    if (value === null || value === undefined) return '<span class="warn">조회 실패</span>';
    return value.toLocaleString("ko-KR", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
  }
}