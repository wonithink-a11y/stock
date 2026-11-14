/* 오늘 탭 — 디자인 시안 v2(docs/design/prototype-today-v2.html)를 실제 데이터로 옮긴 것.
   한 줄 시황(규칙 생성) · 외국인 순매수 막대 · 업종 트리맵 · 후보 표 · 연동 서랍.
   자료: ../data/sector-strength.json(업종·종목 수익률·시총) · ../data/latest-v2.json(후보 점수) · ../data/market_flows.json(외국인 순매수 19일).
   점수·신뢰도·맥락은 관찰용이다 — 맥락 칸은 파이프라인 3번 설계 전이라 비어 있다. 색·간격은 앱 변수(→ docs/design/tokens.css 브리지)만 쓴다. */
(function () {
  const PT = window.PT;
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (n, d = 2) => Number(n).toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (r) => (r > 0 ? "+" : r < 0 ? "−" : "") + Math.abs(r * 100).toFixed(2) + "%";
  const cls = (r) => (r > 0 ? "td-up" : r < 0 ? "td-down" : "");
  const glyph = (r) => (r > 0 ? "▲" : r < 0 ? "▼" : "―");
  const eok = (v) => (v < 0 ? "−" : "+") + fmt(Math.abs(v), 0) + "억";
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const rgb = (h) => { h = h.replace("#", ""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)); };
  const mix = (a, b, t) => "rgb(" + a.map((x, i) => Math.round(x + (b[i] - x) * t)).join(",") + ")";

  const STYLE = `<style>
  .td{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:16px;align-items:start}
  .td-main{display:flex;flex-direction:column;gap:16px;min-width:0}
  .td-p{background:var(--panel);border:1px solid var(--panel-border);border-radius:8px;min-width:0;overflow:hidden}
  .td-h{display:flex;align-items:center;gap:12px;padding:12px 16px;border-bottom:1px solid var(--panel-border);flex-wrap:wrap}
  .td-h h2{font-size:13px;font-weight:600;margin:0}.td-h .r{margin-left:auto;display:flex;gap:12px;align-items:center}
  .td-dim{color:var(--text-dim);font-size:12px}
  .td-up{color:var(--up)}.td-down{color:var(--down)}
  .td-brief{padding:16px;display:flex;flex-direction:column;gap:12px}
  .td-brief h1{font-size:20px;font-weight:700;margin:0;letter-spacing:-.015em}
  .td-brief p{font-size:16px;line-height:1.55;margin:0}.td-brief b{font-weight:600}
  .td-strip{display:flex;flex-wrap:wrap;gap:8px 24px;padding-top:12px;border-top:1px solid var(--panel-border);color:var(--text-dim);font-size:12px}
  .td-strip b{color:var(--text);margin-left:6px;font-weight:600}
  .td-seg{display:inline-flex;padding:2px;border-radius:4px;background:var(--surface-2)}
  .td-seg button{height:24px;padding:0 10px;border-radius:3px;color:var(--text-dim);font-size:12px;font-weight:500;white-space:nowrap;background:none;border:0;cursor:pointer}
  .td-seg button[aria-pressed="true"]{background:var(--panel);color:var(--text);font-weight:600;box-shadow:0 0 0 1px var(--panel-border)}
  .td-flows{display:grid;grid-template-columns:1fr 1fr}.td-flows>div{padding:12px 16px}.td-flows>div+div{border-left:1px solid var(--panel-border)}
  .td-flows svg{width:100%;height:96px;display:block}
  .td-tbl{width:100%;border-collapse:collapse}
  .td-tbl th{text-align:right;font-size:11px;font-weight:600;color:var(--text-dim);padding:8px 12px;border-bottom:1px solid var(--panel-border);white-space:nowrap}
  .td-tbl td{height:46px;padding:0 12px;text-align:right;border-bottom:1px solid var(--panel-border);white-space:nowrap}
  .td-tbl th:first-child,.td-tbl td:first-child{text-align:left;padding-left:16px;width:32px;color:var(--text-dim)}
  .td-tbl th:nth-child(2),.td-tbl td:nth-child(2){text-align:left}
  .td-tbl tbody tr{cursor:pointer}.td-tbl tbody tr:hover{background:var(--row-hover)}
  .td-tbl tbody tr[aria-selected="true"]{background:var(--row-selected);box-shadow:inset 2px 0 0 var(--accent)}
  .td-tbl tr:last-child td{border-bottom:0}
  .td-nm b{font-weight:600}.td-nm span{margin-left:6px;color:var(--text-dim);font-size:12px}
  .td-stack{display:inline-flex;width:96px;height:6px;gap:2px;vertical-align:middle;margin-left:8px}.td-stack i{display:block;height:100%;border-radius:2px;min-width:2px}
  .td-f{background:var(--text)}.td-v{background:var(--text-dim)}.td-t{background:var(--accent)}
  .td-tag{display:inline-flex;align-items:center;height:20px;padding:0 8px;border-radius:4px;font-size:11px;font-weight:600;background:var(--surface-2);color:var(--text-dim)}
  .td-side{position:sticky;top:16px;max-height:calc(100vh - 32px);overflow:auto}
  .td-side .e{padding:32px 24px;color:var(--text-dim);display:flex;flex-direction:column;gap:8px}.td-side .e b{color:var(--text);font-weight:600}
  .td-dh{padding:16px;border-bottom:1px solid var(--panel-border)}
  .td-dh h3{margin:0;font-size:16px;font-weight:700}
  .td-ds{padding:16px;border-bottom:1px solid var(--panel-border);display:flex;flex-direction:column;gap:12px}.td-ds:last-child{border-bottom:0}
  .td-ds h4{margin:0;font-size:11px;font-weight:600;color:var(--text-dim)}
  .td-kv{display:grid;grid-template-columns:repeat(5,1fr);gap:8px}.td-kv div{display:flex;flex-direction:column;gap:2px}.td-kv span{color:var(--text-dim);font-size:11px}.td-kv b{font-size:12px;font-weight:600}
  .td-bar{display:grid;grid-template-columns:48px 1fr 40px;gap:12px;align-items:center;font-size:12px;color:var(--text-dim)}
  .td-bar .t{height:6px;border-radius:999px;background:var(--surface-3);overflow:hidden}.td-bar .t i{display:block;height:100%;border-radius:999px}.td-bar .v{text-align:right;color:var(--text);font-weight:600}
  .td-slot{padding:12px;border:1px solid var(--panel-border);border-radius:4px;color:var(--text-dim);font-size:12px;line-height:1.5}.td-slot b{display:block;color:var(--text);font-weight:600;margin-bottom:2px}
  .td-num{font-variant-numeric:tabular-nums}
  #td-map{position:relative;height:380px}
  @media(max-width:1100px){.td{grid-template-columns:minmax(0,1fr)}.td-side{position:static;max-height:none}}
  @media(max-width:700px){.td-flows{grid-template-columns:1fr}.td-flows>div+div{border-left:0;border-top:1px solid var(--panel-border)}.td-hide{display:none}}
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
  function barsSvg(series) {
    if (!series.length) return '<span class="td-dim">자료 없음</span>';
    const W = 300, H = 96, p = 4, mx = Math.max(...series.map((s) => Math.abs(s.v))) || 1, bw = (W - 2 * p) / series.length, mid = H / 2;
    const up = css("--up"), down = css("--down");
    return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="외국인 순매수 일별 막대"><line x1="0" x2="${W}" y1="${mid}" y2="${mid}" stroke="${css("--panel-border")}"/>` +
      series.map((s, i) => { const h = Math.abs(s.v) / mx * (mid - p), y = s.v >= 0 ? mid - h : mid; return `<rect x="${(p + i * bw + 1).toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(1, bw - 2).toFixed(1)}" height="${Math.max(1, h).toFixed(1)}" fill="${s.v >= 0 ? up : down}"><title>${s.d.slice(4, 6)}.${s.d.slice(6)} ${eok(s.v)}</title></rect>`; }).join("") + "</svg>";
  }

  window.TABS.today = {
    title: "오늘",
    render: async function (container) {
      const [ss, lv, mf] = await Promise.all([PT.tryFetchJson("../data/sector-strength.json"), PT.tryFetchJson("../data/latest-v2.json"), PT.tryFetchJson("../data/market_flows.json")]);
      if (!ss) { container.innerHTML = '<div class="empty">업종 자료(<code>data/sector-strength.json</code>)를 읽지 못했습니다.</div>'; return; }
      const stocks = (ss.stocks || []).filter((s) => s.cap && s.r && ["1d", "1w", "1m", "3m", "6m"].every((k) => s.r[k] != null));
      const RK = ["1d", "1w", "1m", "3m", "6m"], RL = ["1일", "1주", "1개월", "3개월", "6개월"];
      const byT = {};
      stocks.forEach((s) => { byT[s.t] = { t: s.t, n: s.n, g: s.g, cap: s.cap, r: RK.map((k) => s.r[k]) }; });
      const cands = [];
      if (lv && lv.results) {
        lv.results.map((x) => x.result).filter((r) => r.finalScore != null && r.tradeAllowed && ((r.confidence && r.confidence.value) || 0) >= 80)
          .sort((a, b) => b.finalScore - a.finalScore).slice(0, 8).forEach((r) => {
            const c = { t: r.ticker, n: r.name, s: r.finalScore, c: r.confidence.value, comps: ["fundamental", "valuation", "technical", "supplyDemand"].map((k) => (r.components || {})[k] || 0), state: r.tradingState, flags: (r.flags || []).map(String).slice(0, 2) };
            cands.push(c); byT[c.t] = Object.assign(byT[c.t] || { t: c.t, n: c.n }, { score: c.s, conf: c.c, comps: c.comps, state: c.state });
          });
      }
      const asof = String(ss.asof || "");
      const asofTxt = asof.length === 8 ? asof.slice(4, 6) + "." + asof.slice(6) : asof;
      const fK = flowSeries(mf, "KOSPI"), fQ = flowSeries(mf, "KOSDAQ");
      const lastK = fK[fK.length - 1], sum5 = (a) => a.slice(-5).reduce((x, y) => x + y.v, 0);
      const bm = ss.benchmark || {}, cb = ss.capBenchmark || {};

      let narr = `유니버스(코스피200+코스닥150) 종목 수익률 중앙값은 <b class="${cls(bm["1d"])}">${glyph(bm["1d"])} ${pct(bm["1d"])}</b>, 시총가중은 <b class="${cls(cb["1d"])}">${glyph(cb["1d"])} ${pct(cb["1d"])}</b>(1일). `;
      narr += `1개월은 중앙값 <b class="${cls(bm["1m"])}">${pct(bm["1m"])}</b>, 3개월 <b class="${cls(bm["3m"])}">${pct(bm["3m"])}</b>. `;
      if (lastK) narr += `코스피 외국인은 ${lastK.d.slice(4, 6)}.${lastK.d.slice(6)} 하루 <b class="${cls(lastK.v)}">${eok(lastK.v)}</b>(${lastK.v < 0 ? "순매도" : "순매수"}), 최근 5거래일 합계 <b class="${cls(sum5(fK))}">${eok(sum5(fK))}</b>.`;

      container.innerHTML = STYLE + `<div class="td"><div class="td-main">
        <section class="td-p td-brief"><div style="display:flex;align-items:baseline;gap:12px;flex-wrap:wrap"><h1>오늘</h1><span class="td-dim">기준 ${esc(asofTxt)} · 업종 자료 ${stocks.length}종목</span></div>
          <p>${narr}</p>
          <div class="td-strip"><span>유니버스 중앙값 1주<b class="td-num ${cls(bm["1w"])}">${pct(bm["1w"])}</b></span><span>시총가중 1개월<b class="td-num ${cls(cb["1m"])}">${pct(cb["1m"])}</b></span><span>점수 기준일<b class="td-num">${esc(lv ? String((lv.results[0] && lv.results[0].meta && lv.results[0].meta.dataCutoff) || "").replace(/^\d{4}(\d{2})(\d{2})$/, "$1.$2") : "—")}</b></span><span>수급 기준일<b class="td-num">${lastK ? lastK.d.slice(4, 6) + "." + lastK.d.slice(6) : "—"}</b></span></div>
        </section>
        <section class="td-p"><div class="td-h"><h2>외국인 순매수 (억원)</h2><span class="td-dim">일별 · 최근 ${fK.length}거래일</span></div>
          <div class="td-flows"><div><div class="td-dim" style="margin-bottom:6px">코스피 <b class="td-num ${fK.length ? cls(sum5(fK)) : ""}">${fK.length ? "5일 " + eok(sum5(fK)) : ""}</b></div>${barsSvg(fK)}</div><div><div class="td-dim" style="margin-bottom:6px">코스닥 <b class="td-num ${fQ.length ? cls(sum5(fQ)) : ""}">${fQ.length ? "5일 " + eok(sum5(fQ)) : ""}</b></div>${barsSvg(fQ)}</div></div></section>
        <section class="td-p"><div class="td-h"><h2>업종 지도</h2><span class="td-dim td-hide">면적 = 시가총액의 제곱근 · 색 = 수익률(빨강 상승 / 파랑 하락)</span><div class="r"><div class="td-seg" id="td-metric"><button data-k="0" aria-pressed="true">1일</button><button data-k="1" aria-pressed="false">1주</button><button data-k="2" aria-pressed="false">1개월</button></div></div></div><div id="td-map"></div></section>
        <section class="td-p"><div class="td-h"><h2>후보 종목</h2><span class="td-dim td-hide">점수순 · 신뢰도 80 이상 · 거래 가능</span><div class="r"><span class="td-dim"><span class="td-stack" style="width:auto;margin:0"><i class="td-f" style="width:12px"></i><i class="td-v" style="width:12px"></i><i class="td-t" style="width:12px"></i></span> 재무 · 가치 · 기술</span></div></div>
          <div style="overflow-x:auto"><table class="td-tbl"><thead><tr><th>#</th><th>종목</th><th>점수 구성</th><th class="td-hide">신뢰도</th><th id="td-rh">1일</th><th class="td-hide">상태</th></tr></thead><tbody id="td-cands"></tbody></table></div></section>
      </div><aside class="td-p td-side" id="td-side"></aside></div>`;

      let metricK = 0, selected = null;
      const mapEl = container.querySelector("#td-map"), side = container.querySelector("#td-side"), tbody = container.querySelector("#td-cands");
      const nodeColor = (r) => mix(rgb(css("--surface-3")), r >= 0 ? rgb(css("--up")) : rgb(css("--down")), Math.min(1, Math.abs(r) / [0.05, 0.10, 0.20][metricK]) * 0.85);

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
      function drawCands() {
        container.querySelector("#td-rh").textContent = RL[metricK];
        tbody.innerHTML = cands.map((c, i) => {
          const s = byT[c.t], r = s && s.r ? s.r[metricK] : null, w = (x) => Math.max(0, x / 100 * 96);
          return `<tr data-t="${esc(c.t)}" tabindex="0" aria-selected="${selected === c.t}"><td class="td-num">${i + 1}</td><td class="td-nm"><b>${esc(c.n)}</b><span class="td-num">${esc(c.t)}</span></td>` +
            `<td><b class="td-num">${fmt(c.s, 1)}</b><span class="td-stack" title="재무 ${c.comps[0]} · 가치 ${c.comps[1]} · 기술 ${c.comps[2]}"><i class="td-f" style="width:${w(c.comps[0])}px"></i><i class="td-v" style="width:${w(c.comps[1])}px"></i><i class="td-t" style="width:${w(c.comps[2])}px"></i></span></td>` +
            `<td class="td-num td-hide">${fmt(c.c, 1)}</td><td class="td-num ${r === null ? "" : cls(r)}">${r === null ? "—" : glyph(r) + " " + pct(r).replace(/^[+−]/, "")}</td><td class="td-hide"><span class="td-tag">${c.flags.length ? esc(c.flags[0]) : "정상"}</span></td></tr>`;
        }).join("") || '<tr><td colspan="6" class="td-dim" style="text-align:center;height:60px">후보 자료(<code>data/latest-v2.json</code>)를 읽지 못했습니다.</td></tr>';
      }
      function drawSide() {
        const s = selected && byT[selected];
        if (!s) { side.innerHTML = '<div class="e"><b>종목을 선택하세요</b><span>후보 표의 행이나 업종 지도의 칸을 고르면 점수 구성·수익률·맥락이 이곳에 열립니다.</span></div>'; return; }
        const names = ["재무", "가치", "기술", "수급"], cl = ["td-f", "td-v", "td-t", "td-v"];
        side.innerHTML = `<div class="td-dh"><h3>${esc(s.n)}</h3><div class="td-dim"><span class="td-num">${esc(s.t)}</span>${s.g ? " · " + esc(s.g) : ""}${s.cap ? " · 시총 " + fmt(s.cap / 1e12, 2) + "조" : ""}</div>` +
          (s.score !== undefined ? `<div style="display:flex;align-items:baseline;gap:12px;margin-top:8px"><span class="td-num" style="font-size:28px;font-weight:600">${fmt(s.score, 1)}</span><span class="td-dim">점수 · 신뢰도 ${fmt(s.conf, 1)} · ${s.state === "NORMAL" ? "거래 상태 정상" : esc(s.state)}</span></div>` : "") + "</div>" +
          (s.r ? `<div class="td-ds"><h4>수익률</h4><div class="td-kv">${s.r.map((x, i) => `<div><span>${RL[i]}</span><b class="td-num ${cls(x)}">${pct(x)}</b></div>`).join("")}</div></div>` : '<div class="td-ds"><h4>수익률</h4><span class="td-dim">수익률 자료 범위 밖(유니버스 밖)</span></div>') +
          (s.comps ? `<div class="td-ds"><h4>점수 구성 (점)</h4>${s.comps.map((v, i) => `<div class="td-bar"><span>${names[i]}</span><div class="t"><i class="${cl[i]}" style="width:${Math.min(100, v / 50 * 100)}%"></i></div><span class="v td-num">${fmt(v, 1)}</span></div>`).join("")}<span class="td-dim">수급 축은 가중치 0(정책) — 점수에 반영되지 않음</span></div>` : "") +
          `<div class="td-ds"><h4>맥락 (점수에 반영되지 않음)</h4><div class="td-slot"><b>논리 · 반증</b>파이프라인 3번 설계 전 — 연결 예정</div><div class="td-slot"><b>공시 · 뉴스 · 수급</b>종목 맥락 파이프라인 연결 예정</div></div>`;
      }
      function select(t) { if (!byT[t]) return; selected = t; drawSide(); drawCands(); drawMap(); }

      container.querySelector("#td-metric").addEventListener("click", (e) => {
        const b = e.target.closest("button"); if (!b) return;
        container.querySelectorAll("#td-metric button").forEach((x) => x.setAttribute("aria-pressed", x === b));
        metricK = +b.dataset.k; drawMap(); drawCands();
      });
      mapEl.addEventListener("click", (e) => { const g = e.target.closest("g[data-t]"); if (g) select(g.dataset.t); });
      tbody.addEventListener("click", (e) => { const tr = e.target.closest("tr[data-t]"); if (tr) select(tr.dataset.t); });
      tbody.addEventListener("keydown", (e) => { if (e.key === "Enter") { const tr = e.target.closest("tr[data-t]"); if (tr) select(tr.dataset.t); } });
      document.addEventListener("themechange", () => { drawMap(); });
      window.addEventListener("resize", () => { if (container.isConnected && mapEl.clientWidth) drawMap(); });
      drawMap(); drawCands(); drawSide();
    },
  };
})();
