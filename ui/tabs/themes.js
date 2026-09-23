/* 탭 - 테마 (관찰용)
   ① 테마 트리: docs/data/theme-strength.json (daily-analysis 가 매일 갱신)
   ② 테마 × 외부요인 민감도: docs/data/theme-sensitivity.json (월 1회, A2a 뒤)
   메인 대시보드(docs/index.html 섹터강도 탭)와 같은 파일을 읽는다 - 새 계산·수집 없음.
   Pages 에서 이 UI 는 /paper-trading/ 아래라 ../data/ 가 docs/data 다.
   ★ 둘 다 예측 신호가 아니다(테마 선행관계 A형 REJECT, 민감도는 같은 날 반응). */
(function () {
  window.TABS = window.TABS || {};

  var TREE_PATHS = ["../data/theme-strength.json", "data/theme-strength.json"];
  var SENS_PATHS = ["../data/theme-sensitivity.json", "data/theme-sensitivity.json"];
  var WINS = [["1d", "1일"], ["1w", "1주"], ["1m", "1개월"], ["3m", "3개월"]];
  var SENS_LABEL = {
    "Nasdaq-100": ["나스닥100", "나스닥100과 SOX 를 함께 넣은 회귀라 조건부 계수입니다. 게임·인터넷의 나스닥+ / SOX− 는 '반도체를 뺀 나머지 나스닥 기술주' 노출이지, SOX 가 오르면 떨어진다는 뜻이 아닙니다."],
    "SOX": ["반도체(SOX)", "나스닥100 을 통제한 뒤의 반도체 노출(조건부 계수)."],
    "USD/KRW": ["원/달러", "+ = 원화 약세(환율 상승)일에 시장보다 더 오름. 뉴욕 정오 환율 기준."],
    "US10Y": ["미 10년 금리", "금리 1σ 상승일의 반응"],
    "VIX": ["VIX", "VIX 상승(공포)일에 시장보다 덜/더 빠지는지"],
    "WTI": ["유가(WTI)", "유가 1σ 상승일의 반응"]
  };

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function pct(v) {
    if (v == null || !isFinite(v)) return '<span class="dim">-</span>';
    var n = v * 100;
    return '<span style="color:var(' + (n >= 0 ? "--up" : "--down") + ')">' + (n >= 0 ? "+" : "") + n.toFixed(1) + "%</span>";
  }
  async function first(paths) {
    for (var i = 0; i < paths.length; i++) {
      var d = await window.PT.tryFetchJson(paths[i]);
      if (d) return d;
    }
    return null;
  }

  function treeHtml(d, st) {
    var w = st.win;
    var val = function (s) { return s && s.ret ? s.ret[w] : null; };
    var vals = [];
    d.tree.forEach(function (b) { vals.push(val(b.stats)); b.subs.forEach(function (k) { vals.push(val(k.stats)); }); });
    var scale = Math.max.apply(null, [0.01].concat(vals.filter(function (v) { return v != null; }).map(Math.abs)));
    var bar = function (v) {
      if (v == null) return "<td></td>";
      var p = Math.min(100, Math.abs(v) / scale * 100).toFixed(1);
      var c = v >= 0 ? "--up" : "--down";
      return '<td style="width:30%;min-width:80px"><div style="display:flex">' +
        '<div style="flex:1;display:flex;justify-content:flex-end">' + (v < 0 ? '<div style="height:8px;width:' + p + '%;background:var(' + c + ');opacity:.75;border-radius:2px"></div>' : "") + "</div>" +
        '<div style="width:1px;background:var(--panel-border)"></div>' +
        '<div style="flex:1">' + (v >= 0 ? '<div style="height:8px;width:' + p + '%;background:var(' + c + ');opacity:.75;border-radius:2px"></div>' : "") + "</div></div></td>";
    };
    var lead = function (L, members) {
      if (!L) return '<span class="dim">-</span>';
      var m = (members || []).filter(function (x) { return x.t === L.t; })[0];
      return esc(L.name) + (L.primary ? "" : ' <span class="dim">(부)</span>') + " " + pct(m && m.ret ? m.ret[w] : null);
    };
    var row = function (key, label, depth, s, members, L, toggle) {
      var open = st.open[key];
      return "<tr" + (toggle ? ' data-thtoggle="' + esc(key) + '" style="cursor:pointer"' : "") + ">" +
        '<td style="padding-left:' + (6 + depth * 16) + 'px;white-space:nowrap">' +
        (toggle ? '<span class="dim" style="display:inline-block;width:12px">' + (open ? "▾" : "▸") + "</span>" : "") +
        (depth === 0 ? "<b>" + esc(label) + "</b>" : esc(label)) +
        ' <span class="dim" style="font-size:11px">' + (s ? s.n : 0) + "종목</span></td>" +
        '<td style="text-align:right">' + pct(val(s)) + "</td>" + bar(val(s)) +
        '<td style="text-align:right">' + (s ? pct(s.rs[w]) : '<span class="dim">-</span>') + "</td>" +
        '<td style="text-align:right">' + (s && s.breadth20 != null ? Math.round(s.breadth20 * 100) + "%" : '<span class="dim">-</span>') + "</td>" +
        '<td style="font-size:12px">' + lead(L, members) + "</td></tr>";
    };
    var rows = "";
    d.tree.forEach(function (b) {
      rows += row(b.key, b.theme, 0, b.stats, [].concat.apply([], b.subs.map(function (k) { return k.members; })), b.leader, true);
      if (!st.open[b.key]) return;
      b.subs.forEach(function (k) {
        rows += row(k.key, k.theme, 1, k.stats, k.members, k.leader, true);
        if (!st.open[k.key]) return;
        k.members.slice().sort(function (x, y) {
          return ((y.ret || {})[w] == null ? -9 : y.ret[w]) - ((x.ret || {})[w] == null ? -9 : x.ret[w]);
        }).forEach(function (m) {
          var r = m.ret ? m.ret[w] : null;
          rows += '<tr><td style="padding-left:50px;font-size:12px">' + esc(m.name) + ' <span class="dim">' + esc(m.t) + "</span>" +
            (m.primary ? "" : ' <span class="dim">(부)</span>') + "</td>" +
            '<td style="text-align:right;font-size:12px">' + (m.hasPrice ? pct(r) : '<span class="dim">가격 없음</span>') + "</td>" +
            bar(r) + "<td></td><td></td><td></td></tr>";
        });
      });
    });
    var chips = WINS.map(function (x) {
      return '<button class="btn"' + (st.win === x[0] ? ' style="border-color:var(--accent);color:var(--accent)"' : "") +
        ' data-thwin="' + x[0] + '">' + x[1] + "</button>";
    }).join(" ") + ' <button class="btn" data-thtoggle="__all">전체 펼치기/접기</button>';
    return '<section class="panel"><h2>테마 트리 <span class="dim" style="text-transform:none;letter-spacing:0">· 기준일 ' +
      esc(d.asOf) + " · 분류 v" + esc(d.treeVersion) + "(" + esc(d.treeAsOf) + ") · 벤치마크 " + esc(w) + " " + pct((d.benchmark || {})[w]) + "</span></h2>" +
      '<div class="dim" style="font-size:12px;margin-bottom:8px">⚠️ 관찰용 — 테마 소속은 지금 기준으로 손으로 고른 것이라 과거 검증에 쓰지 않습니다. ' +
      "값 = 소속 종목 수익률 중앙값, 상대 = 전 종목 중앙값 대비, 20일선 = 20일 이동평균 위 비율, 대장주 = 지금 시총 1위(주 테마 중). " +
      "(부) 종목은 두 테마에 들어가 두 테마가 같이 움직여 보일 수 있습니다. 한 테마가 다른 테마를 <b>선행한다는 근거는 없습니다</b>(선행관계 A형 REJECT). 줄을 누르면 펼쳐집니다.</div>" +
      '<div style="margin-bottom:8px">' + chips + "</div>" +
      '<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">테마</th><th style="text-align:right">수익률</th>' +
      '<th style="text-align:center">−  |  +</th><th style="text-align:right">상대</th><th style="text-align:right">20일선</th><th style="text-align:left">대장주</th></tr></thead>' +
      "<tbody>" + rows + "</tbody></table></div></section>";
  }

  function sensHtml(d) {
    var VMAX = 80;
    var cell = function (c) {
      if (!c) return '<td class="dim" style="text-align:center">-</td>';
      var strong = Math.abs(c.t) >= 2;
      var p = Math.round(Math.min(Math.abs(c.bp) / VMAX, 1) * (strong ? 70 : 18));
      var col = c.bp >= 0 ? "var(--up)" : "var(--down)";
      return '<td title="t = ' + c.t + " · 표본 " + c.n + '일" style="text-align:center;background:color-mix(in srgb, ' + col + " " + p + "%, transparent);" +
        (strong ? "font-weight:600" : "color:var(--text-dim)") + '">' + (c.bp > 0 ? "+" : "") + Math.round(c.bp) + "</td>";
    };
    var head = d.factors.map(function (f) {
      var L = SENS_LABEL[f] || [f, ""];
      return '<th style="text-align:center;cursor:help" title="' + esc(L[1]) + '">' + esc(L[0]) + (f === "Nasdaq-100" || f === "SOX" ? " ⓘ" : "") + "</th>";
    }).join("");
    var rows = "", prev = null;
    d.themes.forEach(function (th) {
      if (th.big !== prev) {
        rows += '<tr><td colspan="' + (d.factors.length + 1) + '" style="padding-top:8px"><b>' + esc(th.big) + "</b></td></tr>";
        prev = th.big;
      }
      rows += '<tr><td style="padding-left:16px;white-space:nowrap">' + esc(th.sub) + "</td>" +
        d.factors.map(function (f) { return cell(th.cells && th.cells[f]); }).join("") + "</tr>";
    });
    return '<section class="panel"><h2>테마 × 외부요인 민감도 <span class="dim" style="text-transform:none;letter-spacing:0">· ' +
      esc(d.window[0]) + " ~ " + esc(d.window[1]) + " · 월 1회 갱신</span></h2>" +
      '<div class="dim" style="font-size:12px;margin-bottom:8px">⚠️ <b>동시 민감도이며 예측 신호가 아닙니다.</b> 값 = 요인이 평소 크기(1σ)만큼 움직인 날 ' +
      "테마가 시장·규모 대비 <b>추가로</b> 반응한 정도(bp, 빨강 = 같이 오름). 흐린 칸은 |t| &lt; 2. 이 창에서 |t| &gt; 2 는 " + d.absTgt2 + "칸 / " + d.cells +
      "칸 — 우연만으로도 약 " + d.expectedByChance + "칸이 나오니 여러 테마에 걸친 패턴으로 읽으세요. 미국 요인은 전날 밤 값이고 대개 한국 시초가에 이미 반영됩니다. " +
      "ⓘ 열 제목에 마우스를 올리면 해석 주의가 나옵니다.</div>" +
      '<div style="overflow-x:auto"><table><thead><tr><th style="text-align:left">테마</th>' + head + "</tr></thead><tbody>" + rows + "</tbody></table></div></section>";
  }

  window.TABS.themes = {
    title: "테마",
    render: async function (container) {
      var tree = await first(TREE_PATHS);
      var sens = await first(SENS_PATHS);
      var st = { win: "1d", open: {} };
      function draw() {
        try {
          container.innerHTML =
            (tree && tree.tree ? treeHtml(tree, st)
              : '<div class="empty">테마 트리 데이터(data/theme-strength.json)가 아직 없습니다. <span class="dim">평일 16:40 daily-analysis 가 만듭니다.</span></div>') +
            (sens && sens.themes ? sensHtml(sens)
              : '<div class="empty">민감도 데이터(data/theme-sensitivity.json)가 아직 없습니다. <span class="dim">월 1회(A2a 뒤) 갱신됩니다.</span></div>');
        } catch (e) {
          container.innerHTML = '<div class="empty">테마 탭 렌더링 오류<br><span class="dim">' + esc(e && e.message || e) + "</span></div>";
        }
      }
      container.addEventListener("click", function (e) {
        var w = e.target.closest && e.target.closest("[data-thwin]");
        if (w) { st.win = w.getAttribute("data-thwin"); return draw(); }
        var t = e.target.closest && e.target.closest("[data-thtoggle]");
        if (!t || !tree) return;
        var key = t.getAttribute("data-thtoggle");
        if (key === "__all") {
          var keys = [];
          tree.tree.forEach(function (b) { keys.push(b.key); b.subs.forEach(function (k) { keys.push(k.key); }); });
          var openAll = !keys.every(function (k) { return st.open[k]; });
          st.open = {};
          if (openAll) keys.forEach(function (k) { st.open[k] = true; });
        } else {
          st.open[key] = !st.open[key];
        }
        draw();
      });
      draw();
    }
  };
})();
