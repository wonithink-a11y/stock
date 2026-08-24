window.TABS = window.TABS || {};
window.TABS.chart = {
  title: "차트",
  render: async function (container) {
    try {
      const res = await fetch("../data/positions.json");
      if (!res.ok) throw new Error("HTTP " + res.status);
      const data = await res.json();
      renderChartTab(container, data);
    } catch (e) {
      container.innerHTML = '<div class="empty">데이터 로드 실패: ' + String(e && e.message || e) + "</div>";
    }
  }
};

function renderChartTab(container, data) {
  const { updatedAt, historyAsOf, account, strategies } = data;
  const strategyEntries = Object.entries(strategies);
  const totalPositions = strategyEntries.reduce((n, [, s]) => n + (s.positions || []).length, 0);
  const openCount = strategyEntries.reduce((n, [, s]) =>
    n + (s.positions || []).filter((p) => p.status === "OPEN").length, 0);

  let html = "";

  // 계좌 요약 - 히어로 스탯 바 (전문 트레이딩 터미널의 상단 계좌 바 참고)
  html += '<div class="panel account-hero">';
  html += '  <div class="hero-stat"><div class="stat-label">예수금</div><div class="stat-value-lg mono">' + formatAccount(account?.cashKrw) + "</div></div>";
  html += '  <div class="hero-stat"><div class="stat-label">평가금액</div><div class="stat-value-lg mono">' + formatAccount(account?.totalValueKrw) + "</div></div>";
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

  let selectedSymbol = null;
  let selectedPosition = null;

  function buildTables() {
    let tablesHtml = "";
    strategyEntries.forEach(([strategyId, strategy]) => {
      const positions = strategy.positions || [];
      if (positions.length === 0) return;

      tablesHtml += '<div class="panel" style="margin-top:12px;">';
      tablesHtml += '  <h2>' + strategyId + ' (' + positions.length + "건)</h2>";
      tablesHtml += '  <table>';
      tablesHtml += "    <thead><tr>";
      tablesHtml += '      <th>종목</th><th>상태</th><th>수량</th><th>평단가</th><th>현재가</th><th>미실현손익(원)</th><th>미실현손익(%)</th><th>액션</th>';
      tablesHtml += "    </tr></thead><tbody>";

      positions.forEach((pos) => {
        const isSelected = pos.symbol === selectedSymbol;
        const rowClass = isSelected ? ' style="background:#1a2438;"' : "";
        tablesHtml += "<tr" + rowClass + ' data-symbol="' + pos.symbol + '">';
        tablesHtml += '      <td class="mono" style="text-align:left;">' + pos.symbol + "</td>";
        tablesHtml += '      <td><span class="badge ' + getStatusBadgeClass(pos.status) + '">' + pos.status + "</span></td>";
        tablesHtml += '      <td class="mono">' + (pos.quantity ?? "-") + "</td>";
        tablesHtml += '      <td class="mono">' + formatPrice(pos.avgEntryPrice) + "</td>";
        tablesHtml += '      <td class="mono">' + formatPrice(pos.currentPrice) + "</td>";
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
        row.style.background = "#1a2438";
        selectedSymbol = row.dataset.symbol;
        selectedPosition = allPositions.find((p) => p.symbol === selectedSymbol);
        if (selectedPosition) {
          drawChart(selectedPosition.history, selectedPosition.currentPrice, selectedPosition.avgEntryPrice);
          chartTitle.textContent = selectedSymbol + " (" + selectedPosition.strategyId + ")";
        }
      });
      row.addEventListener("mouseenter", () => {
        if (row.dataset.symbol !== selectedSymbol) row.style.background = "#141a26";
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
    tablesContainer.querySelector('tr[data-symbol="' + first.symbol + '"]').style.background = "#1a2438";
    drawChart(first.history, first.currentPrice, first.avgEntryPrice);
    chartTitle.textContent = first.symbol + " (" + first.strategyId + ")";
  }

  function drawChart(history, currentPrice, avgEntryPrice) {
    if (!history || history.length === 0) {
      const ctx = chartCanvas.getContext("2d");
      ctx.clearRect(0, 0, chartCanvas.width, chartCanvas.height);
      ctx.fillStyle = "#7a8494";
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

    ctx.strokeStyle = "#1f2530";
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
      ctx.strokeStyle = "#4da3ff";
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#4da3ff";
      ctx.font = "11px var(--mono)";
      ctx.textAlign = "right";
      ctx.fillText(formatPriceShort(currentPrice) + " (현재가)", width - padding.right + 5, y + 4);
    }

    if (avgEntryPrice && avgEntryPrice >= minPrice && avgEntryPrice <= maxPrice) {
      const y = yScale(avgEntryPrice);
      ctx.strokeStyle = "#e0a72e";
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 6]);
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = "#e0a72e";
      ctx.font = "11px var(--mono)";
      ctx.textAlign = "right";
      ctx.fillText(formatPriceShort(avgEntryPrice) + " (평단가)", width - padding.right + 5, y - 8);
    }

    ctx.strokeStyle = "#4da3ff";
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
    ctx.fillStyle = "#4da3ff";
    ctx.beginPath();
    ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "#0b0e14";
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
      ctx.fillStyle = "#4da3ff";
      ctx.beginPath();
      ctx.arc(x, y, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#0b0e14";
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