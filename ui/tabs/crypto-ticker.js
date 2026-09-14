/* 업비트·빗썸 실계좌 서브탭에 얹는 실시간 시세 패널 - 주요 10종목 현재가·
   24시간 등락률·김치프리미엄, 클릭하면 최근 7일 1시간봉 차트.
   거래소 공개 API(Upbit/Bithumb/Binance)는 Access-Control-Allow-Origin: *
   를 낸다(2026-09-14 실측) - 백엔드 없이 브라우저에서 바로 조회한다. 조회
   전용 원칙과도 맞다(주문 API는 안 쓴다).

   김치프리미엄 = 국내가 / (바이낸스 USDT가 × USDT/KRW) - 1. USDT/KRW는
   업비트 KRW-USDT 시장가를 업비트·빗썸 공통 기준으로 쓴다 - 거래소마다
   따로 재면 각자의 USDT 마켓 유동성 차이가 프리미엄값에 섞여 들어간다. */
window.CryptoTicker = (function () {
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

  // 업비트는 자체 캔들 API, 빗썸은 자체 캔들 API를 각각 쓴다(교차로 빌리지
  // 않는다) - 같은 코인이라도 두 거래소 가격이 갈릴 수 있어 탭이 보여주는
  // 시세와 다른 거래소 차트를 섞으면 헷갈린다.
  async function fetchCandles(exchange, code, count) {
    if (exchange === "upbit") {
      const res = await fetch("https://api.upbit.com/v1/candles/minutes/60?market=KRW-" + code + "&count=" + count);
      if (!res.ok) throw new Error("업비트 차트 HTTP " + res.status);
      return (await res.json()).reverse().map((r) => ({ close: r.trade_price }));
    }
    const res = await fetch("https://api.bithumb.com/public/candlestick/" + code + "_KRW/1h");
    if (!res.ok) throw new Error("빗썸 차트 HTTP " + res.status);
    const j = await res.json();
    if (j.status !== "0000") throw new Error("빗썸 차트 응답 오류 (status " + j.status + ")");
    return j.data.slice(-count).map((r) => ({ close: Number(r[2]) }));
  }

  function lineChartSvg(history) {
    if (!history || history.length < 2) return '<div class="empty">차트 데이터가 부족합니다.</div>';
    const closes = history.map((h) => h.close);
    const min = Math.min(...closes), max = Math.max(...closes), range = max - min || 1;
    const w = 700, h = 160, pad = 8;
    const pts = closes.map((c, i) =>
      ((i / (closes.length - 1)) * (w - pad * 2) + pad).toFixed(1) + "," +
      (h - pad - ((c - min) / range) * (h - pad * 2)).toFixed(1)
    ).join(" ");
    const color = closes[closes.length - 1] >= closes[0] ? "var(--up)" : "var(--down)";
    return '<svg viewBox="0 0 ' + w + " " + h + '" style="width:100%;height:150px" preserveAspectRatio="none">' +
      '<polyline points="' + pts + '" fill="none" style="stroke:' + color + ';stroke-width:1.5;stroke-linejoin:round" /></svg>';
  }

  // 3개 출처(국내가·바이낸스가·USDT환율) 중 하나가 막혀도 나머지는 보여준다
  // - Promise.all은 하나만 실패해도 전체를 던져 패널이 통째로 비었다(교훈57과
  // 같은 모양: 모르는 값이 하나 있다고 아는 값까지 숨기지 않는다).
  async function renderPanel(container, exchange) {
    const PT = window.PT;
    container.innerHTML = '<div class="panel"><h2>시세 · 김치프리미엄</h2><div class="empty">불러오는 중...</div></div>';
    const codes = COINS.map((c) => c.code);

    let domesticR, binanceR, usdtKrwR;
    if (exchange === "upbit") {
      // 업비트 국내가·USDT환율을 한 호출로 합친다(markets에 KRW-USDT를 같이
      // 넣는다) - 따로 두 번 부르면 업비트의 초당 요청 한도에 둘이 같이
      // 걸려 가격은 뜨는데 환율만 실패하는 경우가 있었다(2026-09-15 실측 -
      // 김치프리미엄 칸만 전부 빈 증상으로 나타났다).
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

    if (domesticR.status === "rejected" && binanceR.status === "rejected" && usdtKrwR.status === "rejected") {
      container.innerHTML = '<div class="panel"><h2>시세 · 김치프리미엄</h2><div class="empty">시세 조회 실패(거래소 API 응답 없음) — 새로고침으로 다시 시도해주세요.</div></div>';
      return;
    }

    const failedParts = [];
    if (domesticR.status === "rejected") failedParts.push((exchange === "upbit" ? "업비트" : "빗썸") + " 시세");
    if (binanceR.status === "rejected") failedParts.push("바이낸스 시세");
    if (usdtKrwR.status === "rejected") failedParts.push("USDT/KRW 환율");

    let html = '<div class="panel"><h2>시세 · 김치프리미엄</h2>' +
      '<div class="dim" style="font-size:11px;margin-bottom:8px">USDT/KRW 기준환율(업비트) ' +
      (usdtKrw ? PT.formatPrice(usdtKrw) + "원" : "—") +
      " · 해외가는 바이낸스 USDT 마켓 · 종목을 클릭하면 차트가 표시됩니다</div>" +
      (failedParts.length ? '<div class="warn" style="font-size:11px;margin-bottom:8px">조회 실패로 일부 값 비어있음: ' +
        failedParts.join(", ") + " (새로고침으로 재시도 가능)</div>" : "") +
      '<table><thead><tr><th>코인</th><th>현재가</th><th>24H 등락</th><th>김치프리미엄</th></tr></thead><tbody>';
    COINS.forEach((c) => {
      const d = domestic[c.code];
      const b = binance[c.code];
      const premiumPct = (d && b && usdtKrw) ? ((d.price / (b * usdtKrw)) - 1) * 100 : null;
      html += '<tr class="ct-row" data-code="' + c.code + '" style="cursor:pointer">' +
        "<td style='text-align:left'>" + c.name + " <span class='mono dim' style='font-size:11px'>" + c.code + "</span></td>" +
        '<td class="mono">' + (d ? PT.formatPrice(d.price) + "원" : "—") + "</td>" +
        '<td class="mono ' + (d ? PT.getPnlClass(d.changePct) : "") + '">' + (d ? PT.formatPnlPct(d.changePct) : "—") + "</td>" +
        '<td class="mono ' + (premiumPct === null ? "" : PT.getPnlClass(premiumPct)) + '">' +
        (premiumPct === null ? "—" : PT.formatPnlPct(premiumPct)) + "</td></tr>";
    });
    html += '</tbody></table><div id="ct-chart-slot" style="margin-top:10px"></div></div>';
    container.innerHTML = html;

    const slot = document.getElementById("ct-chart-slot");
    container.querySelectorAll(".ct-row").forEach((row) => {
      row.addEventListener("click", async () => {
        const code = row.dataset.code;
        const name = COINS.find((c) => c.code === code).name;
        slot.innerHTML = '<div class="empty">차트 불러오는 중...</div>';
        try {
          const candles = await withRetry(() => fetchCandles(exchange, code, 168), 1);
          slot.innerHTML = '<div class="dim" style="font-size:11px;margin-bottom:4px">' + name + " · 최근 7일(1시간봉)</div>" +
            lineChartSvg(candles);
        } catch (e) {
          slot.innerHTML = '<div class="empty">차트 조회 실패: ' + String((e && e.message) || e) + "</div>";
        }
      });
    });
  }

  return { renderPanel };
})();
