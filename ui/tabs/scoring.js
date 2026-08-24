/* 탭2 - 스코어링 (별개 운영 시스템 데이터 뷰어, Paper Trading Engine과 무관)
   원격 3개 JSON(latest/recommendations/portfolio)을 raw URL로 fetch해서
   요약 카드 + 종목 스코어 테이블 + 추천 성과 + 포트폴리오 조언으로 보여준다.
   소스별 fail-soft: 어느 하나가 실패해도 해당 섹션만 안내 문구로 비운다. */
(function () {
  window.TABS = window.TABS || {};

  var SRC = {
    latest: "https://raw.githubusercontent.com/wonithink-a11y/stock/main/docs/data/latest.json",
    recs: "https://raw.githubusercontent.com/wonithink-a11y/stock/main/docs/data/recommendations.json",
    portfolio: "https://raw.githubusercontent.com/wonithink-a11y/stock/main/docs/data/portfolio.json"
  };

  var AXES = [
    ["fundamental", "펀더"],
    ["valuation", "밸류"],
    ["technical", "기술"],
    ["supplyDemand", "수급"]
  ];

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fmt(n, d) {
    if (n == null || typeof n !== "number" || !isFinite(n)) return "-";
    return n.toLocaleString("ko-KR", { maximumFractionDigits: d == null ? 0 : d });
  }

  function signed(n, d) {
    if (n == null || typeof n !== "number" || !isFinite(n)) return "-";
    var s = n > 0 ? "+" : "";
    return s + n.toLocaleString("ko-KR", { maximumFractionDigits: d == null ? 1 : d });
  }

  /* 한국 관례 색상 매핑: A(강력매수)=빨강 강조, B=초록, C=중립 회색,
     D/E(부정~매도)=파랑. 점수도 마찬가지로 높으면 빨강, 낮으면 파랑. */
  function gradeMeta(grade) {
    var c = String(grade || "").trim().charAt(0).toUpperCase();
    switch (c) {
      case "A": return { col: "var(--up)", weight: 700 };
      case "B": return { col: "#35c07a", weight: 400 };
      case "C": return { col: "var(--text-dim)", weight: 400 };
      case "D": return { col: "var(--down)", weight: 400 };
      case "E": return { col: "var(--down)", weight: 700 };
      default: return { col: "var(--text-dim)", weight: 400 };
    }
  }

  function gradeBadge(grade) {
    var m = gradeMeta(grade);
    return '<span class="badge" style="color:' + m.col + ";font-weight:" + m.weight + '">' +
      esc(grade || "-") + "</span>";
  }

  function scoreClass(n) {
    if (n == null || typeof n !== "number" || !isFinite(n)) return "dim";
    if (n >= 75) return "up";
    if (n <= 45) return "down";
    return "";
  }

  function fetchJson(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function failBox(label) {
    return '<div class="empty">' + esc(label) +
      " 데이터를 불러오지 못했습니다.<br><span class=\"dim\">네트워크 상태를 확인하거나 잠시 후 다시 열어주세요.</span></div>";
  }

  /* 패널 안에 들어가는 미니 카드(.panel 중첩을 피하기 위한 인라인 스타일) */
  function miniCard(label, valueHtml, subHtml) {
    return '<div style="border:1px solid var(--panel-border);border-radius:6px;background:#141926;' +
      "padding:10px 14px\">" +
      '<div class="stat-label">' + label + "</div>" +
      '<div style="margin:2px 0">' + valueHtml + "</div>" +
      '<div class="dim" style="font-size:11px">' + subHtml + "</div></div>";
  }

  /* ---- 요약 카드 ------------------------------------------------------ */
  function summaryCards(latest) {
    var results = (latest && latest.results) || [];
    var regime = (latest && latest.regime) || {};
    var abCount = results.filter(function (r) { return /^[AB]/i.test(String(r.grade || "")); }).length;
    var updated = latest && latest.updatedAt ? String(latest.updatedAt).slice(0, 10) : "-";
    var cards = [
      ["시장 레짐",
        '<span class="stat-value ' + scoreClass(regime.score) + '">' + esc(regime.grade || "-") + "</span>",
        "레짐 점수 " + fmt(regime.score, 1)],
      ["스코어링 대상",
        '<span class="stat-value">' + fmt(results.length) + "</span>",
        "KR " + fmt(results.filter(function (r) { return r.market === "KR"; }).length) +
        " · US " + fmt(results.filter(function (r) { return r.market === "US"; }).length)],
      ["A·B 등급 (매수 후보)",
        '<span class="stat-value up">' + fmt(abCount) + "</span>",
        "전체 중 상위 등급"],
      ["데이터 기준",
        '<span class="stat-value" style="font-size:16px">' + esc(updated) + "</span>",
        "updatedAt (UTC)"]
    ];
    return cards.map(function (c) { return miniCard(c[0], c[1], c[2]); }).join("");
  }

  /* ---- 상위 종목 카드 -------------------------------------------------- */
  function topCards(results) {
    var top = results.slice()
      .sort(function (a, b) { return (b.totalScore || 0) - (a.totalScore || 0); })
      .slice(0, 8);
    if (top.length === 0) return '<div class="empty">표시할 종목이 없습니다.</div>';
    return '<div class="grid grid-4">' + top.map(function (r, i) {
      return miniCard(
        "#" + (i + 1) + " · " + esc(r.ticker) + " · " + esc(r.market || "-"),
        '<span style="display:flex;justify-content:space-between;align-items:baseline;gap:6px">' +
        '<span class="stat-value ' + scoreClass(r.totalScore) + '">' + fmt(r.totalScore, 1) + "</span>" +
        gradeBadge(r.grade) + "</span>",
        esc(r.name || r.ticker));
    }).join("") + "</div>";
  }

  /* ---- 전체 스코어 테이블 ---------------------------------------------- */
  function scoreTableHtml(results) {
    var rows = results.slice()
      .sort(function (a, b) { return (b.totalScore || 0) - (a.totalScore || 0); });

    var axisCell = function (r, key) {
      var box = r && r.breakdown && r.breakdown[key];
      var s = box && typeof box.score === "number" ? box.score : null;
      var w = s == null ? 0 : Math.max(0, Math.min(100, s));
      var barCol = s == null ? "transparent"
        : s >= 70 ? "#35c07a" : s >= 50 ? "var(--warn)" : "var(--down)";
      return "<td>" +
        '<div style="display:flex;align-items:center;gap:6px;justify-content:flex-end">' +
        '<div style="width:52px;height:5px;background:#1a2030;border-radius:3px;overflow:hidden">' +
        '<div style="width:' + w + "%;height:100%;background:" + barCol + '"></div></div>' +
        '<span class="' + (s == null ? "dim" : "") + '" style="font-size:11px;min-width:30px;text-align:right">' +
        (s == null ? "-" : s.toFixed(0)) + "</span></div></td>";
    };

    var body = rows.map(function (r, i) {
      var warns = (r.warnings || []).filter(Boolean);
      return "<tr>" +
        '<td class="dim">' + (i + 1) + "</td>" +
        '<td class="mono dim">' + esc(r.ticker) + "</td>" +
        "<td>" + esc(r.name || "-") + "</td>" +
        '<td class="dim">' + esc(r.market || "-") + "</td>" +
        '<td class="' + scoreClass(r.totalScore) + '" style="font-weight:600;font-size:14px">' +
        fmt(r.totalScore, 1) + "</td>" +
        "<td>" + gradeBadge(r.grade) + "</td>" +
        AXES.map(function (a) { return axisCell(r, a[0]); }).join("") +
        "<td>" + fmt(r.currentPrice) + "</td>" +
        '<td class="dim">' +
        (r.dataCoverage && r.dataCoverage.overall != null
          ? Math.round(r.dataCoverage.overall * 100) + "%" : "-") + "</td>" +
        '<td class="warn" style="font-size:11px;max-width:140px">' +
        esc(warns.length ? warns.join(", ") : "-") + "</td>" +
        "</tr>";
    }).join("");

    return "<table><thead><tr>" +
      "<th>#</th><th>티커</th><th>종목명</th><th>시장</th><th>총점</th><th>등급</th>" +
      AXES.map(function (a) { return "<th>" + a[1] + "</th>"; }).join("") +
      "<th>현재가</th><th>커버리지</th><th>경고</th>" +
      "</tr></thead><tbody>" + body + "</tbody></table>";
  }

  /* ---- 추천 성과 -------------------------------------------------------- */
  function recsSection(recs) {
    var perf = (recs && recs.performance) || [];
    if (perf.length === 0) return '<div class="empty">추천 이력이 없습니다.</div>';

    var open = perf.filter(function (p) { return p.status === "open"; });
    var wins = open.filter(function (p) { return (p.changePct || 0) > 0; });
    var avg = open.length
      ? open.reduce(function (s, p) { return s + (p.changePct || 0); }, 0) / open.length
      : null;
    var best = open.reduce(function (m, p) {
      return !m || (p.changePct || 0) > (m.changePct || 0) ? p : m;
    }, null);

    var stats =
      miniCard("진행 중 추천", '<span class="stat-value">' + fmt(open.length) + "건</span>", "status: open / 전체 " + fmt(perf.length) + "건") +
      miniCard("평균 수익률",
        '<span class="stat-value ' + (avg == null ? "" : avg >= 0 ? "up" : "down") + '">' + signed(avg, 2) + "%</span>",
        "open 추천 기준") +
      miniCard("승률",
        '<span class="stat-value up">' + (open.length ? fmt(wins.length / open.length * 100, 1) : "-") + "%</span>",
        fmt(wins.length) + " / " + fmt(open.length) + " (+)") +
      miniCard("최고 성과",
        '<span class="stat-value ' + (best && best.changePct > 0 ? "up" : "down") + '">' +
        (best ? signed(best.changePct, 2) + "%" : "-") + "</span>",
        best ? esc(best.name || "") : "");

    var recent = perf.slice().sort(function (a, b) {
      return String(b.recommendedDate || "").localeCompare(String(a.recommendedDate || ""));
    }).slice(0, 25);

    var chgCell = function (v) {
      var cls = v == null ? "dim" : v > 0 ? "up" : v < 0 ? "down" : "dim";
      return '<td class="' + cls + '" style="font-weight:600">' + signed(v, 2) + "%</td>";
    };

    var table =
      "<table><thead><tr>" +
      "<th>추천일</th><th>티커</th><th>종목명</th><th>시장</th><th>추천가</th><th>현재가</th>" +
      "<th>수익률</th><th>보유일</th><th>당시점수</th><th>당시등급</th><th>상태</th>" +
      "</tr></thead><tbody>" +
      recent.map(function (p) {
        return "<tr>" +
          '<td class="dim">' + esc(p.recommendedDate || "-") + "</td>" +
          '<td class="mono dim">' + esc(p.ticker) + "</td>" +
          "<td>" + esc(p.name || "-") + "</td>" +
          '<td class="dim">' + esc(p.market || "-") + "</td>" +
          "<td>" + fmt(p.priceAtRecommendation) + "</td>" +
          "<td>" + fmt(p.currentPrice) + "</td>" +
          chgCell(typeof p.changePct === "number" ? p.changePct : null) +
          "<td>" + fmt(p.holdingDays) + "</td>" +
          '<td class="' + scoreClass(p.scoreAtRecommendation) + '">' + fmt(p.scoreAtRecommendation, 1) + "</td>" +
          "<td>" + gradeBadge(p.gradeAtRecommendation) + "</td>" +
          '<td><span class="badge status-open">' + esc(p.status || "-") + "</span></td>" +
          "</tr>";
      }).join("") +
      "</tbody></table>" +
      '<div class="dim" style="font-size:11px;padding-top:8px">최근 25건만 표시 · 전체 ' +
      fmt(perf.length) + "건</div>";

    return '<div class="grid grid-4" style="margin-bottom:12px">' + stats + "</div>" + table;
  }

  /* ---- 포트폴리오 조언 --------------------------------------------------- */
  function portSection(port) {
    var holdings = (port && port.holdings) || [];
    if (holdings.length === 0) return '<div class="empty">보유 포지션이 없습니다.</div>';

    var table =
      "<table><thead><tr>" +
      "<th>티커</th><th>종목명</th><th>수량</th><th>평단</th><th>현재가</th><th>평가액</th>" +
      "<th>평가손익</th><th>손익률</th><th>스코어</th><th>등급</th>" +
      "</tr></thead><tbody>" +
      holdings.map(function (h) {
        var pnlCls = (h.unrealizedPnL || 0) > 0 ? "up"
          : (h.unrealizedPnL || 0) < 0 ? "down" : "dim";
        return "<tr>" +
          '<td class="mono dim">' + esc(h.ticker) + "</td>" +
          "<td>" + esc(h.name || "-") + "</td>" +
          "<td>" + fmt(h.quantity) + "</td>" +
          "<td>" + fmt(h.avgPrice) + "</td>" +
          "<td>" + fmt(h.currentPrice) + "</td>" +
          "<td>" + fmt(h.currentValue) + "</td>" +
          '<td class="' + pnlCls + '">' + signed(h.unrealizedPnL) + "</td>" +
          '<td class="' + pnlCls + '" style="font-weight:600">' + signed(h.unrealizedPnLPct, 2) + "%</td>" +
          '<td class="' + scoreClass(h.stockScore) + '">' + fmt(h.stockScore, 1) + "</td>" +
          "<td>" + gradeBadge(h.stockGrade) + "</td>" +
          "</tr>";
      }).join("") +
      "</tbody></table>";

    var advice = holdings.map(function (h) {
      return '<div style="border-left:2px solid var(--accent);padding:4px 10px;margin-top:8px">' +
        '<span class="mono dim" style="font-size:11px">' + esc(h.ticker) + "</span> " +
        '<span class="warn" style="font-weight:600">' + esc(h.referenceSignal || "-") + "</span>" +
        '<div class="dim" style="font-size:12px;margin-top:2px">' + esc(h.signalReason || "") + "</div>" +
        ((h.stockWarnings || []).length
          ? '<div class="warn" style="font-size:11px;margin-top:2px">경고: ' +
            esc(h.stockWarnings.join(", ")) + "</div>"
          : "") +
        "</div>";
    }).join("");

    return table + '<div style="padding-top:6px">' + advice + "</div>";
  }

  window.TABS.scoring = {
    title: "스코어링",
    render: async function (container) {
      var res = await Promise.allSettled([
        fetchJson(SRC.latest),
        fetchJson(SRC.recs),
        fetchJson(SRC.portfolio)
      ]);
      var latest = res[0].status === "fulfilled" ? res[0].value : null;
      var recs = res[1].status === "fulfilled" ? res[1].value : null;
      var port = res[2].status === "fulfilled" ? res[2].value : null;

      /* 세 소스 전부 실패한 경우에만 탭 전체 안내 문구. 개별 실패는 각
         섹션 안내 문구로 흡수해 나머지 섹션은 정상 렌더한다(fail-soft). */
      if (!latest && !recs && !port) {
        container.innerHTML = failBox("스코어링");
        return;
      }

      container.innerHTML = "";

      if (latest) {
        try {
          container.insertAdjacentHTML("beforeend",
            '<div class="grid grid-4">' + summaryCards(latest) + "</div>");
        } catch (e) { /* fail-soft */ }

        try {
          container.insertAdjacentHTML("beforeend",
            '<section class="panel"><h2>상위 종목 TOP 8</h2>' + topCards(latest.results || []) + "</section>");
        } catch (e) {
          container.insertAdjacentHTML("beforeend",
            '<section class="panel">' + failBox("상위 종목") + "</section>");
        }

        try {
          var results = latest.results || [];
          container.insertAdjacentHTML("beforeend",
            '<section class="panel"><h2>전체 종목 스코어 (' + results.length + "종목, 총점순)</h2>" +
            (results.length ? scoreTableHtml(results) : '<div class="empty">스코어링 결과가 없습니다.</div>') +
            "</section>");
        } catch (e) {
          container.insertAdjacentHTML("beforeend",
            '<section class="panel">' + failBox("종목 스코어") + "</section>");
        }
      } else {
        container.insertAdjacentHTML("beforeend",
          '<section class="panel">' + failBox("스코어링 결과") + "</section>");
      }

      if (recs) {
        try {
          container.insertAdjacentHTML("beforeend",
            '<section class="panel"><h2>추천 성과 트래킹</h2>' + recsSection(recs) + "</section>");
        } catch (e) {
          container.insertAdjacentHTML("beforeend",
            '<section class="panel">' + failBox("추천 성과") + "</section>");
        }
      } else {
        container.insertAdjacentHTML("beforeend",
          '<section class="panel">' + failBox("추천 성과") + "</section>");
      }

      if (port) {
        try {
          container.insertAdjacentHTML("beforeend",
            '<section class="panel"><h2>포트폴리오 조언' +
            (port.marketRegime ? ' <span class="badge" style="color:var(--warn)">시장 레짐: ' +
              esc(port.marketRegime) + "</span>" : "") +
            "</h2>" + portSection(port) + "</section>");
        } catch (e) {
          container.insertAdjacentHTML("beforeend",
            '<section class="panel">' + failBox("포트폴리오") + "</section>");
        }
      } else {
        container.insertAdjacentHTML("beforeend",
          '<section class="panel">' + failBox("포트폴리오") + "</section>");
      }
    }
  };
})();
