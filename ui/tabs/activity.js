/* 거래 내역 탭 - Signals와 Orders를 하나로 합쳤다(2026-09-14 개편, 설계 결정).
   이유: 이 엔진은 신호의 방향·확률·기대값을 저장하지 않고, 주문 원장도
   체결가·상태이력(FSM) 없이 최소 필드만 남긴다(설계 의도 - KIS 체결내역이
   정본). 실제로 있는 건 "오늘 진행 중인 주문"과 "날짜별 체결 요약"뿐이라
   Signals/Orders 두 탭으로 나누면 둘 다 반쯤 빈 화면이 된다. 데이터:
   ui/data/positions.json의 trades(pending[]/days[]/byStrategy). */
window.TABS = window.TABS || {};
window.TABS.activity = {
  title: "거래 내역",
  render: async function (container) {
    const PT = window.PT;
    let data;
    try {
      data = await PT.fetchJson("data/positions.json");
    } catch (e) {
      container.innerHTML = '<div class="empty">데이터 로드 실패: ' + String(e.message || e) + "</div>";
      return;
    }
    container.innerHTML = tradesPanelHtml(data.trades, PT);
  },
};

function tradesPanelHtml(trades, PT) {
  if (!trades) return '<div class="panel"><h2>거래 내역</h2><div class="empty">데이터 없음</div></div>';
  let out = '<div class="panel"><h2>거래 내역 (' + (trades.fromDate || "?") + " ~ " + (trades.toDate || "?") + ")</h2>";
  out += '<div class="dim" style="font-size:11.5px;margin-bottom:10px">신호(매수/매도 판단의 확률·기대값)는 이 엔진이 기록하지 않습니다 — ' +
    "실제 접수·체결된 주문만 표시합니다.</div>";

  if (trades.error) {
    return out + '<div class="empty">체결내역을 못 읽었습니다: ' + trades.error +
      '<br><span class="dim">없는 것이 아니라 못 본 것입니다 - 금액을 0으로 표시하지 않습니다.</span></div></div>';
  }

  const pending = trades.pending || [];
  out += '<h3 style="margin:4px 0 8px">진행 중인 주문 ' + pending.length + '건 <span class="dim" style="font-weight:400;font-size:11px">— 오늘 주문만(KRX 주문은 당일 유효)</span></h3>';
  if (pending.length) {
    out += '<div style="overflow-x:auto"><table><thead><tr><th>주문일</th><th>전략</th><th>종목</th><th>구분</th><th>주문</th><th>체결</th><th>미체결</th></tr></thead><tbody>';
    pending.forEach((o) => {
      out += "<tr>" +
        '<td class="mono">' + o.date + "</td>" +
        '<td class="mono' + (o.strategy ? '">' + o.strategy : ' dim">기록없음') + "</td>" +
        '<td style="text-align:left">' + (o.name || "") + ' <span class="mono dim" style="font-size:11px">' + o.symbol + "</span></td>" +
        '<td><span class="badge ' + (o.side === "SELL" ? "status-submitted" : "status-pending") + '">' +
        (o.side === "SELL" ? "매도" : "매수") + "</span></td>" +
        '<td class="mono">' + o.orderedQty + "</td><td class=\"mono\">" + o.filledQty + "</td>" +
        '<td class="mono warn">' + o.pendingQty + "</td></tr>";
    });
    out += "</tbody></table></div>";
  } else {
    out += '<div class="dim" style="margin-bottom:8px">진행 중인 주문 없음 — 오늘 낸 주문 중 미체결 잔량이 남은 것이 없습니다.</div>';
  }

  const days = trades.days || [];
  if (!days.length) return out + '<div class="empty" style="margin-top:10px">이 기간에 체결된 매매가 없습니다.</div></div>';

  const sum = days.reduce((a, d) => ({
    buy: a.buy + d.buyKrw, sell: a.sell + d.sellKrw,
    realized: a.realized + (d.realizedKrw || 0), rFrom: a.rFrom + (d.realizedFrom || 0),
  }), { buy: 0, sell: 0, realized: 0, rFrom: 0 });

  const byStrategy = trades.byStrategy || {};
  const perDate = {};
  Object.entries(byStrategy).forEach(([sid, sdays]) => {
    (sdays || []).forEach((d) => { (perDate[d.date] = perDate[d.date] || []).push({ sid, d }); });
  });

  out += '<h3 style="margin:16px 0 8px">날짜별 체결 ' + days.length + "일</h3>";
  out += '<div style="overflow-x:auto"><table><thead><tr><th>날짜</th><th>전략</th><th>매수금액</th><th>매수건</th><th>매도금액</th><th>매도건</th><th>순매수</th><th>실현손익</th></tr></thead><tbody>';
  const dayRow = (dateCell, label, labelClass, d) =>
    "<tr>" + '<td class="mono">' + dateCell + "</td>" +
    '<td class="mono ' + labelClass + '">' + label + "</td>" +
    '<td class="mono up">' + (d.buyKrw ? PT.formatAccount(d.buyKrw) : "-") + "</td>" +
    '<td class="mono dim">' + (d.buyCount || "-") + "</td>" +
    '<td class="mono down">' + (d.sellKrw ? PT.formatAccount(d.sellKrw) : "-") + "</td>" +
    '<td class="mono dim">' + (d.sellCount || "-") + "</td>" +
    '<td class="mono ' + PT.getPnlClass(d.netKrw) + '">' + PT.formatPnl(d.netKrw) + "</td>" +
    '<td class="mono ' + (d.realizedFrom ? PT.getPnlClass(d.realizedKrw) : "dim") + '">' +
    (d.realizedFrom ? PT.formatPnl(d.realizedKrw) +
      (d.realizedFrom < d.sellCount ? ' <span class="dim" style="font-size:10px">' + d.realizedFrom + "/" + d.sellCount + "</span>" : "")
      : (d.sellCount ? "기록없음" : "-")) + "</td></tr>";
  days.forEach((d) => {
    const parts = perDate[d.date] || [];
    parts.forEach(({ sid, d: sd }, i) => { out += dayRow(i === 0 ? d.date : "", sid, "", sd); });
    const rest = {
      buyKrw: d.buyKrw - parts.reduce((a, p) => a + p.d.buyKrw, 0),
      sellKrw: d.sellKrw - parts.reduce((a, p) => a + p.d.sellKrw, 0),
      buyCount: d.buyCount - parts.reduce((a, p) => a + p.d.buyCount, 0),
      sellCount: d.sellCount - parts.reduce((a, p) => a + p.d.sellCount, 0),
      realizedKrw: 0, realizedFrom: 0,
    };
    rest.netKrw = rest.buyKrw - rest.sellKrw;
    if (rest.buyKrw || rest.sellKrw) out += dayRow(parts.length ? "" : d.date, "기록없음", "dim", rest);
  });
  out += '</tbody><tfoot><tr><th>합계</th><th class="dim">계좌 전체</th>' +
    '<th class="mono up">' + PT.formatAccount(sum.buy) + "</th><th></th>" +
    '<th class="mono down">' + PT.formatAccount(sum.sell) + "</th><th></th>" +
    '<th class="mono ' + PT.getPnlClass(sum.buy - sum.sell) + '">' + PT.formatPnl(sum.buy - sum.sell) + "</th>" +
    '<th class="mono ' + (sum.rFrom ? PT.getPnlClass(sum.realized) : "dim") + '">' + (sum.rFrom ? PT.formatPnl(sum.realized) : "-") + "</th></tr></tfoot>";
  out += "</table></div>";
  const un = trades.unattributed || {};
  out += '<div class="dim" style="font-size:11px;margin-top:8px">체결분만 셉니다(미체결은 위 표로 갑니다). ' +
    "전략 귀속은 엔진이 주문을 낼 때 남긴 <b>주문번호→전략</b> 원장으로만 합니다. " +
    (un.count ? '<b>기록없음 ' + un.count + "건</b>(매수 " + PT.formatAccount(un.buyKrw) + " · 매도 " + PT.formatAccount(un.sellKrw) + ")은 원장 이전 주문이라 되살릴 수 없습니다." : "") +
    " 실현손익 = (체결평균가 − 진입가) × 체결수량, <b>수수료·세금 전</b>입니다. KIS 일별주문체결 조회는 3개월까지만 줍니다.</div>";
  return out + "</div>";
}
