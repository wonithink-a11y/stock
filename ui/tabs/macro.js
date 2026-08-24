/* 탭4 - 매크로 (ui/data/macro.json 뷰어)
   10개 시계열 카드+스파크라인, 미국 매크로 레짐 스냅샷, 미제공 지표
   (notAvailable)을 명시적으로 표시한다. 데이터가 없는 항목은 임의로
   채우지 않고 "데이터 없음"으로 보여준다. */
(function () {
  window.TABS = window.TABS || {};

  /* fetch는 document 기준으로 해석되므로(ui/index.html 기준) 후보 경로를
     순서대로 시도한다(배포 루트 차이 흡수). */
  var MACRO_PATHS = ["data/macro.json", "../data/macro.json", "ui/data/macro.json"];

  var REGIME_LABELS = {
    yieldcurve: "장단기 금리차 (10Y-2Y)",
    hyspread: "하이일드 스프레드",
    vix: "VIX 변동성지수",
    liquidity: "유동성 (M2 YoY)",
    dollar: "달러 인덱스",
    style: "성장/가치 스타일",
    breadth: "시장 참여 폭 (Breadth)",
    cape: "CAPE (Shiller P/E)"
  };

  var NA_LABELS = {
    gold: "금 (Gold)",
    silver: "은 (Silver)",
    sp500: "S&P 500",
    nasdaq100: "나스닥 100"
  };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmtVal(v) {
    if (v == null || typeof v !== "number" || !isFinite(v)) return "-";
    if (Math.abs(v) >= 1000) return v.toLocaleString("ko-KR", { maximumFractionDigits: 0 });
    return String(Math.round(v * 100) / 100);
  }

  function signed(n, d) {
    if (n == null || typeof n !== "number" || !isFinite(n)) return "";
    var s = n > 0 ? "+" : n < 0 ? "" : "";
    return s + (Math.round(n * Math.pow(10, d == null ? 2 : d)) / Math.pow(10, d == null ? 2 : d))
      .toLocaleString("ko-KR");
  }

  function fetchFirst(paths) {
    return paths.reduce(function (chain, path) {
      return chain.catch(function () {
        return fetch(path).then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        });
      });
    }, Promise.reject());
  }

  /* ---- 스파크라인 ------------------------------------------------------
     마지막 ~90포인트를 viewBox 정규화해 그린다. 방향에 따라 선 색을
     한국 관례(상승 빨강/하락 파랑)로 칠한다. 값이 2개 미만이면 생략. */
  function sparkline(history) {
    var pts = (history || []).filter(function (p) {
      return p && typeof p.value === "number" && isFinite(p.value);
    }).slice(-90);
    if (pts.length < 2) return "";

    var vs = pts.map(function (p) { return p.value; });
    var mn = Math.min.apply(null, vs), mx = Math.max.apply(null, vs);
    var rg = (mx - mn) || 1;
    var W = 100, H = 28, PAD = 3;

    var xy = pts.map(function (p, i) {
      return [
        PAD + (W - 2 * PAD) * i / (pts.length - 1),
        H - PAD - (H - 2 * PAD) * (p.value - mn) / rg
      ];
    });
    var line = xy.map(function (q) { return q[0].toFixed(1) + "," + q[1].toFixed(1); }).join(" ");
    var last = xy[xy.length - 1];
    var first = xy[0];
    var stroke = last[1] < first[1] ? "var(--up)" : last[1] > first[1] ? "var(--down)" : "var(--text-dim)";

    return '<svg viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none" ' +
      'style="width:100%;height:' + H + 'px;display:block;margin-top:6px">' +
      '<polyline points="' + line + '" fill="none" stroke="' + stroke +
      '" stroke-width="1.5" vector-effect="non-scaling-stroke"/>' +
      '<circle cx="' + last[0].toFixed(1) + '" cy="' + last[1].toFixed(1) +
      '" r="1.6" fill="' + stroke + '"/></svg>';
  }

  /* ---- 시계열 카드 ------------------------------------------------------ */
  function seriesCard(key, s) {
    var hist = (s && s.history) || [];
    var valid = hist.filter(function (p) { return p && typeof p.value === "number" && isFinite(p.value); });
    var lastP = valid[valid.length - 1];
    var label = (s && s.label) || key;

    /* 최근 ~20영업일 전 값 대비 변화 */
    var refIdx = Math.max(0, valid.length - 21);
    var prevP = valid[refIdx];
    var diffHtml = "", rangeHtml = "";
    if (lastP && prevP && refIdx < valid.length - 1) {
      var diff = lastP.value - prevP.value;
      var pct = prevP.value !== 0 ? diff / Math.abs(prevP.value) * 100 : null;
      var cls = diff > 0 ? "up" : diff < 0 ? "down" : "dim";
      diffHtml = '<span class="' + cls + '" style="font-size:12px;font-family:var(--mono)">' +
        signed(diff, diff === 0 ? 0 : undefined) +
        (pct != null && pct !== 0 ? " (" + signed(pct, 2) + "%)" : "") + "</span>";
    }
    if (lastP) {
      rangeHtml = '<div class="dim" style="font-size:10px;margin-top:4px">' +
        esc(String(lastP.date || "")) + " 기준 · " + fmtVal(mn(valid)) + " ~ " + fmtVal(mx(valid)) + "</div>";
    }

    return '<div class="panel" style="margin:0;padding:10px 14px">' +
      '<div class="stat-label" title="' + esc(label) + '">' + esc(label) + "</div>" +
      '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">' +
      '<span class="stat-value">' + (lastP ? fmtVal(lastP.value) : "-") + "</span>" +
      diffHtml + "</div>" +
      sparkline(hist) + rangeHtml + "</div>";

    function mn(a) { return a.reduce(function (m, p) { return p.value < m ? p.value : m; }, Infinity); }
    function mx(a) { return a.reduce(function (m, p) { return p.value > m ? p.value : m; }, -Infinity); }
  }

  /* ---- 레짐 스냅샷 ------------------------------------------------------ */
  function signalBadge(signal) {
    var map = {
      green: { col: "#35c07a", text: "안정" },
      yellow: { col: "var(--warn)", text: "주의" },
      red: { col: "var(--up)", text: "위험" },
      neutral: { col: "var(--text-dim)", text: "중립" }
    };
    var m = map[String(signal || "").toLowerCase()] || map.neutral;
    return '<span class="badge" style="color:' + m.col + '">' + m.text + "</span>";
  }

  function regimeCard(it) {
    var label = REGIME_LABELS[it.key] || it.key;
    return '<div class="panel" style="margin:0;padding:10px 14px">' +
      '<div class="stat-label">' + esc(label) + "</div>" +
      '<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">' +
      '<span class="stat-value" style="font-size:19px">' + esc(it.display != null ? it.display : "-") + "</span>" +
      signalBadge(it.signal) + "</div>" +
      '<div class="dim" style="font-size:10px;margin-top:4px">기준일 ' + esc(it.asOf || "-") + "</div></div>";
  }

  window.TABS.macro = {
    title: "매크로",
    render: async function (container) {
      var data;
      try {
        data = await fetchFirst(MACRO_PATHS);
      } catch (e) {
        container.innerHTML =
          '<div class="empty">매크로 데이터(data/macro.json)를 불러오지 못했습니다.<br>' +
          '<span class="dim">파일이 없거나 HTTP 서버로 열지 않은 경우 발생합니다. ' +
          "다른 탭에는 영향이 없습니다.</span></div>";
        return;
      }

      try {
        var series = (data && data.series) || {};
        var snapshot = (data && data.usRegimeSnapshot) || [];
        var notAvail = (data && data.notAvailable) || [];
        var keys = Object.keys(series);

        container.innerHTML =
          /* 헤더 */
          '<section class="panel"><h2>매크로 모니터' +
          (data.seriesAsOf ? ' <span class="dim" style="text-transform:none;letter-spacing:0">· 시계열 기준 ' +
            esc(data.seriesAsOf) + "</span>" : "") +
          "</h2></section>" +

          /* 10개 시계열 카드 */
          '<section class="panel"><h2>핵심 지표 시계열 (' + keys.length + "개)</h2>" +
          (keys.length
            ? '<div class="grid grid-4">' + keys.map(function (k) { return seriesCard(k, series[k]); }).join("") + "</div>"
            : '<div class="empty">시계열 데이터가 없습니다.</div>') +
          "</section>" +

          /* 미국 매크로 레짐 스냅샷 */
          '<section class="panel"><h2>미국 매크로 레짐 스냅샷 (최신값)</h2>' +
          (snapshot.length
            ? '<div class="grid grid-4">' + snapshot.map(regimeCard).join("") + "</div>"
            : '<div class="empty">레짐 스냅샷 데이터가 없습니다.</div>') +
          "</section>" +

          /* 미제공 지표 - 명시적 표시(임의 수치로 채우지 않음) */
          '<section class="panel"><h2>미제공 지표</h2>' +
          (notAvail.length
            ? '<div class="grid grid-4">' + notAvail.map(function (key) {
              var label = NA_LABELS[key] || key;
              return '<div class="panel" style="margin:0;padding:10px 14px;border-style:dashed">' +
                '<div class="stat-label">' + esc(label) + "</div>" +
                '<div class="stat-value dim" style="font-size:18px">N/A</div>' +
                '<div class="dim" style="font-size:11px;margin-top:4px">데이터 없음 · 추가 예정</div></div>';
            }).join("") + "</div>"
            : '<div class="empty">미제공 지표 정보가 없습니다.</div>') +
          "</section>";
      } catch (e) {
        container.innerHTML =
          '<div class="empty">매크로 데이터 렌더링 중 오류가 발생했습니다.<br>' +
          '<span class="dim">' + esc(e && e.message || e) + "</span></div>";
      }
    }
  };
})();
