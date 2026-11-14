/* 오늘 탭 — 디자인 시안 B(docs/design/prototype-b-terminal.html)를 실제 데이터로 옮긴 것.
   타일 두 줄 · 시장 폭 게이지 · 상승/하락 상위 · 지수 선+수급 · 탭 종목 표(+검색) · 수급 테이프 · 업종 지도 · 종목 서랍.
   자료: ../data/sector-strength.json(업종·종목 수익률·시총, 코스피200+코스닥150 352종목) · ../data/latest-v2.json(후보 점수)
        · ../data/market_flows.json(외국인 순매수 19일) · ../data/kospi200fut_history.json(코스피200 현물 일별).
   ★ 여기 숫자는 '유니버스(코스피200+코스닥150)' 기준이지 코스피·코스닥 지수가 아니다(sector-strength.json capBenchmarkNote) — 라벨에 '시장'이라 쓰지 않는다.
   점수·신뢰도·맥락은 관찰용이다 — 맥락 칸은 파이프라인 3번 설계 전이라 비어 있다. 색·간격은 앱 변수(→ docs/design/tokens.css 브리지)만 쓴다. */
(function () {
  const PT = window.PT;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (n, d = 2) => Number(n).toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (r) => (r > 0 ? "+" : r < 0 ? "−" : "") + Math.abs(r * 100).toFixed(2) + "%";
  const cls = (r) => (r > 0 ? "td-up" : r < 0 ? "td-down" : "");
  const glyph = (r) => (r > 0 ? "▲" : r < 0 ? "▼" : "―");
  const eok = (v) => (v < 0 ? "−" : "+") + fmt(Math.abs(v), 0) + "억";
  const md = (d) => { d = String(d).replace(/-/g, ""); return d.slice(4, 6) + "." + d.slice(6, 8); };
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const rgb = (h) => { h = h.replace("#", ""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)); };
  const mix = (a, b, t) => "rgb(" + a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(",") + ")";
  const chip = (r) => `<span class="td-chip ${cls(r)}">${glyph(r)} ${pct(r)}</span>`;

  const STYLE = `<style>
  .td{display:flex;flex-direction:column;gap:12px;min-width:0}
  .td-p{background:var(--panel);border:1px solid var(--panel-border);border-radius:8px;min-width:0;overflow:hidden;display:flex;flex-direction:column}
  .td-h{display:flex;align-items:center;gap:12px;padding:10px 14px;border-bottom:1px solid var(--panel-border);flex-wrap:wrap}
  .td-h h2{font-size:13px;font-weight:600;margin:0}.td-h .r{margin-left:auto;display:flex;gap:8px;align-items:center}
  .td-dim{color:var(--text-dim);font-size:12px}
  .td-up{color:var(--up)}.td-down{color:var(--down)}
  .td-num{font-variant-numeric:tabular-nums}
  .td-chip{display:inline-block;padding:0 6px;border-radius:4px;font-size:11px;font-weight:600;font-variant-numeric:tabular-nums;background:var(--surface-2);color:var(--text-dim)}
  .td-chip.td-up{background:color-mix(in srgb,var(--up) 14%,transparent)}.td-chip.td-down{background:color-mix(in srgb,var(--down) 14%,transparent)}
  .td-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:8px}
  .td-tile{padding:8px 12px;border:1px solid var(--panel-border);border-radius:8px;background:var(--panel);min-width:0}
  .td-tile .a{display:flex;gap:6px;align-items:baseline;white-space:nowrap;overflow:hidden}.td-tile .a b{font-size:12px;font-weight:600}.td-tile .a small{color:var(--text-dim);font-size:10px}
  .td-tile .v{font-size:18px;font-weight:600;margin:2px 0 4px;font-variant-numeric:tabular-nums}
  .td-tiles.sm .td-tile{padding:6px 10px}.td-tiles.sm .v{font-size:14px;margin:1px 0 3px}
  .td-g{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
  .td-s2{grid-column:span 2}
  .td-sc{overflow:auto;max-height:340px}.td-sc.tall{max-height:420px}
  .td-seg{display:inline-flex;padding:2px;border-radius:4px;background:var(--surface-2)}
  .td-seg button{height:22px;padding:0 9px;border-radius:3px;color:var(--text-dim);font-size:12px;font-weight:500;white-space:nowrap;background:none;border:0;cursor:pointer}
  .td-seg button[aria-pressed="true"]{background:var(--panel);color:var(--text);font-weight:600;box-shadow:0 0 0 1px var(--panel-border)}
  .td-tbl{width:100%;border-collapse:collapse}
  .td-tbl th{position:sticky;top:0;background:var(--panel);text-align:right;font-size:11px;font-weight:600;color:var(--text-dim);padding:7px 10px;border-bottom:1px solid var(--panel-border);white-space:nowrap}
  .td-tbl td{height:34px;padding:0 10px;text-align:right;border-bottom:1px solid var(--panel-border);white-space:nowrap}
  .td-tbl th:first-child,.td-tbl td:first-child,.td-tbl th.l,.td-tbl td.l{text-align:left}
  .td-tbl tbody tr[data-t]{cursor:pointer}.td-tbl tbody tr:hover{background:var(--row-hover)}
  .td-tbl tr:last-child td{border-bottom:0}
  .td-nm{max-width:150px;overflow:hidden;text-overflow:ellipsis}.td-nm b{font-weight:600;margin-right:8px}.td-nm span{color:var(--text-dim);font-size:12px}
  .td-sec{color:var(--text-dim);max-width:96px;overflow:hidden;text-overflow:ellipsis}
  .td-stack{display:inline-flex;width:54px;height:5px;gap:1px;vertical-align:middle;margin-left:8px}.td-stack i{display:block;height:100%;border-radius:2px;min-width:2px}
  .td-f{background:var(--text)}.td-v{background:var(--text-dim)}.td-t{background:var(--accent)}
  .td-tabs{display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid var(--panel-border);flex-wrap:wrap;align-items:center}
  .td-tabs button{height:26px;padding:0 12px;border-radius:6px;color:var(--text-dim);font-size:12px;font-weight:500;background:none;border:0;cursor:pointer}
  .td-tabs button:hover{background:var(--surface-2)}.td-tabs button[aria-pressed="true"]{background:var(--accent);color:#fff;font-weight:600}
  .td-tabs input{margin-left:auto;height:26px;width:170px;max-width:100%;padding:0 8px;border:1px solid var(--panel-border);border-radius:6px;background:var(--surface-2);color:var(--text);font:inherit;font-size:12px}
  .td-gauge{padding:8px 14px 2px;text-align:center}.td-gauge svg{width:200px;height:112px}.td-gauge .l{font-size:14px;font-weight:600;margin-top:-6px}
  .td-kvr{display:flex;justify-content:space-between;padding:5px 14px;border-top:1px solid var(--panel-border);font-size:12px}.td-kvr span:first-child{color:var(--text-dim)}
  .td-dv{position:relative;display:inline-block;width:80px;height:8px;vertical-align:middle;margin-right:6px}.td-dv::before{content:"";position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--panel-border)}.td-dv i{position:absolute;top:0;bottom:0;border-radius:1px}
  .td-ch svg{width:100%;display:block}
  #td-map{position:relative;height:380px}
  .td-slot{padding:12px;border:1px solid var(--panel-border);border-radius:4px;color:var(--text-dim);font-size:12px;line-height:1.5}.td-slot b{display:block;color:var(--text);font-weight:600;margin-bottom:2px}
  .td-drawer{position:fixed;top:0;right:0;bottom:0;width:340px;max-width:100%;z-index:40;background:var(--panel);border-left:1px solid var(--panel-border);transform:translateX(100%);transition:transform .12s;overflow:auto}
  .td-drawer.open{transform:none}
  .td-dh{padding:16px;border-bottom:1px solid var(--panel-border);position:relative}.td-dh h3{margin:0;font-size:16px;font-weight:700;padding-right:28px}
  .td-x{position:absolute;top:10px;right:10px;width:28px;height:28px;border-radius:6px;color:var(--text-dim);background:none;border:0;cursor:pointer;font-size:16px}.td-x:hover{background:var(--surface-2)}
  .td-ds{padding:16px;border-bottom:1px solid var(--panel-border);display:flex;flex-direction:column;gap:12px}.td-ds:last-child{border-bottom:0}
  .td-ds h4{margin:0;font-size:11px;font-weight:600;color:var(--text-dim)}
  .td-kv{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.td-kv div{display:flex;flex-direction:column;gap:2px}.td-kv span{color:var(--text-dim);font-size:11px}.td-kv b{font-size:12px;font-weight:600}
  .td-bar{display:grid;grid-template-columns:48px 1fr 40px;gap:12px;align-items:center;font-size:12px;color:var(--text-dim)}
  .td-bar .t{height:6px;border-radius:999px;background:var(--surface-3);overflow:hidden}.td-bar .t i{display:block;height:100%;border-radius:999px}.td-bar .v{text-align:right;color:var(--text);font-weight:600}
  @media(max-width:760px){.td-s2{grid-column:auto}.td-hide{display:none}.td-g{grid-template-columns:minmax(0,1fr)}}
  </style>`;

  function squarify(nodes, x, y, w, h) {
    if (!nodes.length || w <= 0 || h <= 0) return;
    const total = nodes.reduce((a, n) => a + n.v, 0), k = (w * h) / total;
    nodes.forEach((n) => { n.a = n.v * k; });
    let rest = nodes.slice();
    const worst = (row, sum, side) => { const mx = Math.max(...row.map((n) => n.a)), mn = Math.min(...row.map((n) => n.a)), s2 = side * side; return Math.max(s2 * mx / (sum * sum), (sum * sum) / (s2 * mn)); };
    while (rest.length) {
      const side = Math.min(w, h); let row = [rest[0]], sum = rest[0].a, wr = worst(row, sum, side);
      for (let i = 1; i < rest.length; i++) { const s2 = sum + rest[i].a, r2 = worst(row.concat(rest[i]), s2, side); if (r2 > wr) break; row.push(rest[i]); sum = s2; wr = r2; }
      const th = sum / side;
      if (w >= h) { let yy = y; row.forEach((n) => { const hh = n.a / th; Object.assign(n, { x, y: yy, w: th, h: hh }); yy += hh; }); x += th; w -= th; }
      else { let xx = x; row.forEach((n) => { const ww = n.a / th; Object.assign(n, { x: xx, y, w: ww, h: th }); xx += ww; }); y += th; h -= th; }
      rest = rest.slice(row.length);
    }
  }

  function flowSeries(mf, market) {
    const days = ((mf && mf.markets && mf.markets[market] && mf.markets[market].days) || []).slice().sort((a, b) => a.date.localeCompare(b.date));
    return days.map((d) => { const it = d.items.find((i) => i.name === "외국인"); return it ? { d: d.date, v: Math.round(it.net / 1e8) } : null; }).filter(Boolean);
  }
  function barsSvg(series, H) {
    if (!series.length) return '<span class="td-dim">자료 없음</span>';
    const W = 400, p = 4, mx = Math.max(...series.map((s) => Math.abs(s.v))) || 1, bw = (W - 2 * p) / series.length, mid = H / 2;
    const up = css("--up"), down = css("--down");
    return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:${H}px" role="img" aria-label="외국인 순매수 일별 막대"><line x1="0" x2="${W}" y1="${mid}" y2="${mid}" stroke="${css("--panel-border")}"/>` +
      series.map((s, i) => { const h = Math.abs(s.v) / mx * (mid - p), y = s.v >= 0 ? mid - h : mid; return `<rect x="${(p + i * bw + 1).toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(1, bw - 2).toFixed(1)}" height="${Math.max(1, h).toFixed(1)}" fill="${s.v >= 0 ? up : down}"><title>${md(s.d)} ${eok(s.v)}</title></rect>`; }).join("") + "</svg>";
  }
  function lineSvg(series) {
    if (series.length < 2) return '<span class="td-dim">자료 없음</span>';
    const W = 400, H = 190, p = 6, vs = series.map((s) => s.v), lo = Math.min(...vs), hi = Math.max(...vs), pad = (hi - lo) * 0.08 || 1;
    const X = (i) => p + i * (W - 2 * p) / (series.length - 1), Y = (v) => H - p - (v - (lo - pad)) / (hi - lo + 2 * pad) * (H - 2 * p);
    const pts = series.map((s, i) => X(i).toFixed(1) + "," + Y(s.v).toFixed(1)).join(" "), acc = css("--accent");
    return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:${H}px" role="img" aria-label="코스피200 현물 일별 종가">` +
      `<polygon points="${p},${H - p} ${pts} ${W - p},${H - p}" fill="${acc}" fill-opacity=".12"/><polyline points="${pts}" fill="none" stroke="${acc}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>` +
      series.map((s, i) => `<circle cx="${X(i).toFixed(1)}" cy="${Y(s.v).toFixed(1)}" r="6" fill="transparent"><title>${md(s.d)} ${fmt(s.v)}</title></circle>`).join("") + "</svg>";
  }

  window.TABS.today = {
    title: "오늘",
    render: async function (container) {
      const [ss, lv, mf, fut] = await Promise.all([PT.tryFetchJson("../data/sector-strength.json"), PT.tryFetchJson("../data/latest-v2.json"), PT.tryFetchJson("../data/market_flows.json"), PT.tryFetchJson("../data/kospi200fut_history.json")]);
      if (!ss) { container.innerHTML = '<div class="empty">업종 자료(<code>data/sector-strength.json</code>)를 읽지 못했습니다.</div>'; return; }
      const RK = ["1d", "1w", "1m", "3m", "6m"], RL = ["1일", "1주", "1개월", "3개월", "6개월"];
      const stocks = (ss.stocks || []).filter((s) => s.cap && s.r && RK.every((k) => s.r[k] != null)), N = stocks.length;
      const byT = {};
      stocks.forEach((s) => { byT[s.t] = { t: s.t, n: s.n, g: s.g, cap: s.cap, r: RK.map((k) => s.r[k]) }; });
      const cands = [];
      if (lv && lv.results) {
        lv.results.map((x) => x.result).filter((r) => r.finalScore != null && r.tradeAllowed && ((r.confidence && r.confidence.value) || 0) >= 80)
          .sort((a, b) => b.finalScore - a.finalScore).slice(0, 8).forEach((r) => {
            const c = { t: r.ticker, n: r.name, s: r.finalScore, c: r.confidence.value, comps: ["fundamental", "valuation", "technical", "supplyDemand"].map((k) => (r.components || {})[k] || 0), state: r.tradingState, flags: (r.flags || []).map(String).slice(0, 2) };
            cands.push(c); byT[c.t] = Object.assign(byT[c.t] || { t: c.t, n: c.n }, { score: c.s, conf: c.c, comps: c.comps, state: c.state, flags: c.flags });
          });
      }
      const all = Object.values(byT);
      const asof = String(ss.asOf || ss.updatedAt || "").replace(/\D/g, "").slice(0, 8);
      const bm = ss.benchmark || {}, cb = ss.capBenchmark || {};
      const fK = flowSeries(mf, "KOSPI"), fQ = flowSeries(mf, "KOSDAQ"), sum5 = (a) => a.slice(-5).reduce((x, y) => x + y.v, 0);
      const spot = (Array.isArray(fut) ? fut : []).filter((x) => x.spot != null).map((x) => ({ d: x.date, v: x.spot }));
      const upN = stocks.filter((s) => s.r["1d"] > 0).length, dnN = stocks.filter((s) => s.r["1d"] < 0).length;

      const tile = (n, s, v, c) => `<div class="td-tile"><div class="a"><b>${esc(n)}</b><small>${esc(s)}</small></div><div class="v">${v}</div><div>${c}</div></div>`;
      const t1 = [];
      if (spot.length > 1) { const L = spot[spot.length - 1], P = spot[spot.length - 2]; t1.push(tile("코스피200", "현물 " + md(L.d), fmt(L.v), chip(L.v / P.v - 1))); }
      t1.push(tile("시총가중 1일", "코스피200+코스닥150", `<span class="${cls(cb["1d"])}">${pct(cb["1d"])}</span>`, `<span class="td-chip">중앙값 ${pct(bm["1d"])}</span>`));
      t1.push(tile("상승 비율", "1일 · " + N + "종목", (upN / N * 100).toFixed(1) + "%", `<span class="td-chip">상승 ${upN} · 하락 ${dnN}</span>`));
      if (fK.length) t1.push(tile("외국인 코스피", "5일 순매수", `<span class="${cls(sum5(fK))}">${eok(sum5(fK))}</span>`, `<span class="td-chip ${cls(fK[fK.length - 1].v)}">${md(fK[fK.length - 1].d)} ${eok(fK[fK.length - 1].v)}</span>`));
      if (fQ.length) t1.push(tile("외국인 코스닥", "5일 순매수", `<span class="${cls(sum5(fQ))}">${eok(sum5(fQ))}</span>`, `<span class="td-chip ${cls(fQ[fQ.length - 1].v)}">${md(fQ[fQ.length - 1].d)} ${eok(fQ[fQ.length - 1].v)}</span>`));
      if (cands.length) t1.push(tile("후보 최고점", cands[0].n, fmt(cands[0].s, 1), `<span class="td-chip">후보 ${cands.length}개</span>`));
      const gs = {}; stocks.forEach((s) => { const g = (gs[s.g] = gs[s.g] || { n: s.g, cap: 0, w: 0, c: 0 }); g.cap += s.cap; g.w += s.cap * s.r["1d"]; g.c++; });
      const t2 = Object.values(gs).sort((a, b) => b.cap - a.cap).slice(0, 14).map((g) => tile(g.n, g.c + "종목", fmt(g.cap / 1e12, 1) + "조", chip(g.w / g.cap))).join("");

      const sh = (k) => stocks.filter((s) => s.r[RK[k]] > 0).length / N, r0 = sh(0), th = Math.PI * (1 - r0);
      const gauge = `<svg viewBox="0 0 200 118" role="img" aria-label="상승 종목 비율 ${(r0 * 100).toFixed(1)}%"><defs><linearGradient id="td-gg"><stop offset="0" style="stop-color:var(--down)"/><stop offset=".5" style="stop-color:var(--surface-3)"/><stop offset="1" style="stop-color:var(--up)"/></linearGradient></defs><path d="M16 104A84 84 0 0 1 184 104" fill="none" stroke="url(#td-gg)" stroke-width="12" stroke-linecap="round"/><line x1="100" y1="104" x2="${(100 + 66 * Math.cos(th)).toFixed(1)}" y2="${(104 - 66 * Math.sin(th)).toFixed(1)}" stroke="var(--text)" stroke-width="2.5" stroke-linecap="round"/><circle cx="100" cy="104" r="5" fill="var(--text)"/><text x="12" y="116" font-size="10" fill="var(--text-dim)">약세</text><text x="188" y="116" font-size="10" fill="var(--text-dim)" text-anchor="end">강세</text></svg><div class="l"><span class="td-num">${(r0 * 100).toFixed(0)}%</span> ${r0 > .6 ? "강세" : r0 > .4 ? "중립" : "약세"}</div>`;
      const kvr = (a, b) => `<div class="td-kvr"><span>${a}</span><span class="td-num">${b}</span></div>`;
      const kvs = kvr("상승 / 하락 (1일)", upN + " / " + dnN) + [1, 2, 3, 4].map((k) => kvr("상승 비율 " + RL[k], (sh(k) * 100).toFixed(0) + "%")).join("") + kvr("시총가중 1일", `<span class="${cls(cb["1d"])}">${pct(cb["1d"])}</span>`) + kvr("유니버스 중앙값 1일", `<span class="${cls(bm["1d"])}">${pct(bm["1d"])}</span>`);

      const lst = (sorted) => '<table class="td-tbl"><tbody>' + sorted.slice(0, 30).map((s) => `<tr data-t="${esc(s.t)}" tabindex="0"><td class="td-nm l"><b class="td-num">${esc(s.t)}</b><span>${esc(s.n)}</span></td><td class="td-num td-dim">${fmt(s.cap / 1e12, 2)}조</td><td>${chip(s.r[0])}</td></tr>`).join("") + "</tbody></table>";

      const TABS = {
        gain: ["상승 상위", () => all.filter((s) => s.r).sort((a, b) => b.r[0] - a.r[0])], loss: ["하락 상위", () => all.filter((s) => s.r).sort((a, b) => a.r[0] - b.r[0])],
        cap: ["시총 순", () => all.filter((s) => s.cap).sort((a, b) => b.cap - a.cap)], cand: ["후보 점수", () => all.filter((s) => s.score != null).sort((a, b) => b.score - a.score)],
      };
      container.innerHTML = STYLE + `<div class="td">
        <div class="td-tiles">${t1.join("")}</div><div class="td-tiles sm">${t2}</div>
        <div class="td-g">
          <section class="td-p"><div class="td-h"><h2>시장 폭</h2><span class="td-dim">유니버스 ${N}종목 · 기준 ${esc(md(asof))}</span></div><div class="td-gauge">${gauge}</div>${kvs}</section>
          <section class="td-p"><div class="td-h"><h2>상승 상위 · 1일</h2></div><div class="td-sc">${lst([...stocks.map((s) => byT[s.t])].sort((a, b) => b.r[0] - a.r[0]))}</div></section>
          <section class="td-p"><div class="td-h"><h2>하락 상위 · 1일</h2></div><div class="td-sc">${lst([...stocks.map((s) => byT[s.t])].sort((a, b) => a.r[0] - b.r[0]))}</div></section>
        </div>
        <div class="td-g">
          <section class="td-p td-ch"><div class="td-h"><h2>코스피200 현물 · 외국인(코스피)</h2><div class="r"><div class="td-seg" id="td-range"><button data-n="21" aria-pressed="false">1M</button><button data-n="63" aria-pressed="true">3M</button><button data-n="9999" aria-pressed="false">전체</button></div></div></div><div id="td-line" style="padding:6px 8px 0"></div><div style="padding:0 8px 8px;border-top:1px solid var(--panel-border);margin-top:4px"><div class="td-dim" style="padding:4px 6px">외국인 순매수 일별(억원) · 최근 ${fK.length}거래일</div>${barsSvg(fK, 70)}</div></section>
          <section class="td-p td-s2"><div class="td-tabs" id="td-tabs">${Object.entries(TABS).map(([k, [l]]) => `<button data-k="${k}" aria-pressed="${k === "cand"}">${l}</button>`).join("")}<input id="td-q" type="search" placeholder="종목·코드·업종 검색" aria-label="종목 검색"></div><div class="td-sc tall"><table class="td-tbl" id="td-mv"></table></div></section>
          <section class="td-p"><div class="td-h"><h2>외국인 수급 테이프</h2><div class="r"><div class="td-seg" id="td-mk"><button data-m="K" aria-pressed="true">코스피</button><button data-m="Q" aria-pressed="false">코스닥</button></div></div></div><div class="td-sc tall"><table class="td-tbl" id="td-tape"></table></div></section>
        </div>
        <section class="td-p"><div class="td-h"><h2>업종 지도</h2><span class="td-dim td-hide">면적 = 시가총액의 제곱근 · 색 = 수익률(빨강 상승 / 파랑 하락)</span><div class="r"><div class="td-seg" id="td-metric"><button data-k="0" aria-pressed="true">1일</button><button data-k="1" aria-pressed="false">1주</button><button data-k="2" aria-pressed="false">1개월</button></div></div></div><div id="td-map"></div></section>
        <section class="td-p"><div class="td-slot" style="border:0"><b>맥락 · 공시 (점수에 반영되지 않음)</b>파이프라인 3번(논리·반증) 설계 전 — 연결 예정. 위 숫자는 코스피200+코스닥150 유니버스 기준이며 코스피·코스닥 지수가 아니다.</div></section>
      </div><aside class="td-drawer" id="td-drawer" aria-label="종목 상세"></aside>`;

      let metricK = 0, selected = null, tab = "cand", query = "", mk = "K";
      const q = (s) => container.querySelector(s), mapEl = q("#td-map"), drawer = q("#td-drawer");
      const nodeColor = (r) => mix(rgb(css("--surface-3")), r >= 0 ? rgb(css("--up")) : rgb(css("--down")), Math.min(1, Math.abs(r) / [0.05, 0.10, 0.20][metricK]) * 0.85);

      function drawLine(n) { q("#td-line").innerHTML = lineSvg(spot.slice(-n)); }
      function drawMv() {
        let rows = TABS[tab][1](); const s = query.trim().toLowerCase();
        if (s) rows = all.filter((x) => (x.n + x.t + (x.g || "")).toLowerCase().includes(s)).sort((a, b) => (b.cap || 0) - (a.cap || 0));
        rows = rows.slice(0, s ? 80 : 40);
        const cell = (r) => r == null ? '<td class="td-dim">—</td>' : `<td class="td-num ${cls(r)}">${pct(r)}</td>`;
        q("#td-mv").innerHTML = '<thead><tr><th>#</th><th class="l">종목</th><th class="l td-hide">업종</th><th>1일</th><th>1주</th><th class="td-hide">1개월</th><th class="td-hide">시총</th><th>점수</th></tr></thead><tbody>' +
          (rows.length ? rows.map((x, i) => { const r = x.r || [], tot = x.comps ? x.comps[0] + x.comps[1] + x.comps[2] || 1 : 1, w = (v) => (v / tot * 100).toFixed(0);
            return `<tr data-t="${esc(x.t)}" tabindex="0"><td class="td-num td-dim">${i + 1}</td><td class="td-nm l"><b class="td-num">${esc(x.t)}</b><span>${esc(x.n)}</span></td><td class="td-sec l td-hide">${esc(x.g || "—")}</td>${cell(r[0])}${cell(r[1])}${r[2] == null ? '<td class="td-dim td-hide">—</td>' : `<td class="td-num td-hide ${cls(r[2])}">${pct(r[2])}</td>`}<td class="td-num td-dim td-hide">${x.cap ? fmt(x.cap / 1e12, 2) + "조" : "—"}</td>` +
              `<td class="td-num">${x.score != null ? `<b>${fmt(x.score, 1)}</b><span class="td-stack" title="재무 ${x.comps[0]} · 가치 ${x.comps[1]} · 기술 ${x.comps[2]}"><i class="td-f" style="width:${w(x.comps[0])}%"></i><i class="td-v" style="width:${w(x.comps[1])}%"></i><i class="td-t" style="width:${w(x.comps[2])}%"></i></span>` : '<span class="td-dim">—</span>'}</td></tr>`; }).join("")
            : '<tr><td colspan="8" class="td-dim" style="text-align:center;height:60px">결과 없음</td></tr>') + "</tbody>";
      }
      function drawTape() {
        const f = mk === "K" ? fK : fQ, mx = Math.max(1, ...f.map((x) => Math.abs(x.v))), up = css("--up"), down = css("--down");
        const rows = f.map((x, i) => ({ ...x, s5: f.slice(Math.max(0, i - 4), i + 1).reduce((a, y) => a + y.v, 0) })).reverse();
        q("#td-tape").innerHTML = '<thead><tr><th>일자</th><th class="l">순매수(억)</th><th>5일합</th></tr></thead><tbody>' + (rows.map((x) => `<tr><td class="td-num">${md(x.d)}</td><td class="l"><span class="td-dv"><i style="${x.v >= 0 ? "left:50%" : "right:50%"};width:${(Math.abs(x.v) / mx * 50).toFixed(1)}%;background:${x.v >= 0 ? up : down}"></i></span><span class="td-num ${cls(x.v)}">${eok(x.v).replace("억", "")}</span></td><td class="td-num ${cls(x.s5)}">${eok(x.s5).replace("억", "")}</td></tr>`).join("") || '<tr><td colspan="3" class="td-dim">자료 없음</td></tr>') + "</tbody>";
      }
      function drawMap() {
        const W = mapEl.clientWidth || 600, H = mapEl.clientHeight, groups = {};
        stocks.forEach((s) => { const g = (groups[s.g] = groups[s.g] || { name: s.g, v: 0, kids: [] }); g.kids.push({ s: byT[s.t], v: Math.sqrt(s.cap) }); g.v += Math.sqrt(s.cap); });
        const gl = Object.values(groups).sort((a, b) => b.v - a.v); squarify(gl, 0, 0, W, H);
        let svg = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="업종별 종목 수익률 지도" style="display:block">`;
        const sub = css("--text-dim"), txt = css("--text");
        gl.forEach((g) => {
          const gx = g.x + 1, gy = g.y + 1, gw = g.w - 2, gh = g.h - 2, head = gw > 56 && gh > 40 ? 16 : 0;
          g.kids.sort((a, b) => b.v - a.v); squarify(g.kids, gx, gy + head, gw, gh - head);
          if (head) svg += `<text x="${gx + 2}" y="${gy + 12}" font-size="11" font-weight="600" fill="${sub}" style="pointer-events:none">${esc(g.name)}</text>`;
          g.kids.forEach((k) => {
            const st = k.s, r = st.r[metricK], sel = selected === st.t, w = k.w - 1, h = k.h - 1;
            svg += `<g data-t="${esc(st.t)}" style="cursor:pointer"><rect x="${k.x.toFixed(1)}" y="${k.y.toFixed(1)}" width="${Math.max(0, w).toFixed(1)}" height="${Math.max(0, h).toFixed(1)}" rx="2" fill="${nodeColor(r)}" stroke="${sel ? txt : "none"}" stroke-width="${sel ? 2 : 0}"><title>${esc(st.n)} ${pct(r)} · 시총 ${fmt(st.cap / 1e12, 2)}조</title></rect>`;
            if (w > 44 && h > 28) svg += `<text x="${(k.x + 5).toFixed(1)}" y="${(k.y + 15).toFixed(1)}" font-size="11" font-weight="600" fill="#fff" style="pointer-events:none">${esc(st.n.length > Math.floor(w / 8) ? st.n.slice(0, Math.max(2, Math.floor(w / 8))) + "…" : st.n)}</text><text x="${(k.x + 5).toFixed(1)}" y="${(k.y + 28).toFixed(1)}" font-size="10" fill="#fff" fill-opacity=".85" style="pointer-events:none">${pct(r)}</text>`;
            svg += "</g>";
          });
        });
        mapEl.innerHTML = svg + "</svg>";
      }
      function drawDrawer() {
        const s = selected && byT[selected]; if (!s) { drawer.classList.remove("open"); return; }
        const names = ["재무", "가치", "기술", "수급"], cl = ["td-f", "td-v", "td-t", "td-v"];
        drawer.innerHTML = `<div class="td-dh"><button class="td-x" id="td-close" aria-label="닫기">✕</button><h3>${esc(s.n)}</h3><div class="td-dim"><span class="td-num">${esc(s.t)}</span>${s.g ? " · " + esc(s.g) : ""}${s.cap ? " · 시총 " + fmt(s.cap / 1e12, 2) + "조" : ""}</div>` +
          (s.score !== undefined ? `<div style="display:flex;align-items:baseline;gap:12px;margin-top:8px"><span class="td-num" style="font-size:28px;font-weight:600">${fmt(s.score, 1)}</span><span class="td-dim">점수 · 신뢰도 ${fmt(s.conf, 1)} · ${s.state === "NORMAL" ? "거래 상태 정상" : esc(s.state)}</span></div>` : "") + "</div>" +
          (s.r ? `<div class="td-ds"><h4>수익률</h4><div class="td-kv">${s.r.map((x, i) => `<div><span>${RL[i]}</span><b class="td-num ${cls(x)}">${pct(x)}</b></div>`).join("")}</div></div>` : '<div class="td-ds"><h4>수익률</h4><span class="td-dim">수익률 자료 범위 밖(유니버스 밖)</span></div>') +
          (s.comps ? `<div class="td-ds"><h4>점수 구성 (점)</h4>${s.comps.map((v, i) => `<div class="td-bar"><span>${names[i]}</span><div class="t"><i class="${cl[i]}" style="width:${Math.min(100, v / 50 * 100)}%"></i></div><span class="v td-num">${fmt(v, 1)}</span></div>`).join("")}<span class="td-dim">수급 축은 가중치 0(정책) — 점수에 반영되지 않음</span></div>` : "") +
          `<div class="td-ds"><h4>맥락 (점수에 반영되지 않음)</h4><div class="td-slot"><b>논리 · 반증</b>파이프라인 3번 설계 전 — 연결 예정</div><div class="td-slot"><b>공시 · 뉴스 · 수급</b>종목 맥락 파이프라인 연결 예정</div></div>`;
        drawer.classList.add("open");
      }
      function select(t) { if (!byT[t]) return; selected = t; drawDrawer(); drawMap(); }

      container.addEventListener("click", (e) => {
        if (e.target.closest("#td-close")) { selected = null; drawDrawer(); drawMap(); return; }
        const el = e.target.closest("[data-t]"); if (el) select(el.dataset.t);
      });
      container.addEventListener("keydown", (e) => { if (e.key === "Enter") { const el = e.target.closest("tr[data-t]"); if (el) select(el.dataset.t); } else if (e.key === "Escape" && selected) { selected = null; drawDrawer(); drawMap(); } });
      const seg = (id, fn) => q(id).addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; q(id).querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b)); fn(b); });
      seg("#td-range", (b) => drawLine(+b.dataset.n)); seg("#td-metric", (b) => { metricK = +b.dataset.k; drawMap(); }); seg("#td-mk", (b) => { mk = b.dataset.m; drawTape(); });
      q("#td-tabs").addEventListener("click", (e) => { const b = e.target.closest("button"); if (!b) return; tab = b.dataset.k; q("#td-q").value = ""; query = ""; q("#td-tabs").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", x === b)); drawMv(); });
      q("#td-q").addEventListener("input", (e) => { query = e.target.value; drawMv(); });
      document.addEventListener("themechange", () => { drawMap(); drawLine(+q("#td-range [aria-pressed=true]").dataset.n); });
      window.addEventListener("resize", () => { if (container.isConnected && mapEl.clientWidth) drawMap(); });
      drawLine(63); drawMv(); drawTape(); drawMap();
    },
  };
})();
