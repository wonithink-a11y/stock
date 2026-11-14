/* 시장 현황 보드 — 디자인 시안 B(docs/design/prototype-b-terminal.html)를 대시보드 '오늘 > 요약' 맨 위에 옮긴 것.
   index.html 은 세 곳만 건드린다: <script src>, renderToday() 의 `${MktBoard.html()}`, render() 의 MktBoard.mount().
   자료: state.sectorStrength(352종목 · 코스피200+코스닥150) · state.marketFlows(외국인) · latest-v2.json(후보 점수, 지연 로드) · kospi200fut_history.json(현물 일별, 지연 로드).
   ★ 숫자는 '유니버스' 기준이지 코스피·코스닥 지수가 아니다(sector-strength.json capBenchmarkNote). 점수·맥락은 관찰용이며 매매 신호가 아니다.
   종목을 누르면 대시보드의 기존 종목 상세(openStockDetail)가 열린다. 색은 대시보드 변수(→ design/tokens.css)만 쓴다. */
(function () {
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = (n, d = 2) => Number(n).toLocaleString('ko-KR', { minimumFractionDigits: d, maximumFractionDigits: d });
  const pct = (r) => (r > 0 ? '+' : r < 0 ? '−' : '') + Math.abs(r * 100).toFixed(2) + '%';
  const cls = (r) => (r > 0 ? 'mb-up' : r < 0 ? 'mb-down' : '');
  const glyph = (r) => (r > 0 ? '▲' : r < 0 ? '▼' : '―');
  const eok = (v) => (v < 0 ? '−' : '+') + fmt(Math.abs(v), 0) + '억';
  const md = (d) => { d = String(d).replace(/-/g, ''); return d.slice(4, 6) + '.' + d.slice(6, 8); };
  const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const chip = (r) => `<span class="mb-chip ${cls(r)}">${glyph(r)} ${pct(r)}</span>`;
  const RK = ['1d', '1w', '1m', '3m', '6m'], RL = ['1일', '1주', '1개월', '3개월', '6개월'];

  const STYLE = `<style id="mb-style">
  .mb{display:flex;flex-direction:column;gap:10px;margin:0 0 14px}
  .mb-p{background:var(--card);border:1px solid var(--border);border-radius:12px;min-width:0;overflow:hidden;display:flex;flex-direction:column}
  .mb-h{display:flex;align-items:center;gap:10px;padding:9px 14px;border-bottom:1px solid var(--border);flex-wrap:wrap}
  .mb-h h2{font-size:13px;font-weight:600;margin:0}.mb-h .r{margin-left:auto;display:flex;gap:8px;align-items:center}
  .mb-dim{color:var(--muted);font-size:12px}
  .mb-up{color:var(--up)}.mb-down{color:var(--down)}
  .mb-chip{display:inline-block;padding:0 6px;border-radius:4px;font-size:11px;font-weight:600;font-variant-numeric:tabular-nums;background:var(--surface-2);color:var(--muted)}
  .mb-chip.mb-up{background:color-mix(in srgb,var(--up) 14%,transparent)}.mb-chip.mb-down{background:color-mix(in srgb,var(--down) 14%,transparent)}
  .mb-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,150px),1fr));gap:8px}
  .mb-tile{padding:8px 12px;border:1px solid var(--border);border-radius:10px;background:var(--card);min-width:0}
  .mb-tile .a{display:flex;gap:6px;align-items:baseline;white-space:nowrap;overflow:hidden}.mb-tile .a b{font-size:12px;font-weight:600}.mb-tile .a small{color:var(--muted);font-size:10px}
  .mb-tile .v{font-size:18px;font-weight:600;margin:2px 0 4px;font-variant-numeric:tabular-nums}
  .mb-tiles.sm .mb-tile{padding:6px 10px}.mb-tiles.sm .v{font-size:14px;margin:1px 0 3px}
  .mb-g{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:10px}
  .mb-s2{grid-column:span 2}
  .mb-sc{overflow:auto;max-height:340px}.mb-sc.tall{max-height:420px}
  .mb-seg{display:inline-flex;padding:2px;border-radius:5px;background:var(--surface-2)}
  .mb-seg button{height:22px;padding:0 9px;border-radius:4px;color:var(--muted);font-size:12px;font-weight:500;white-space:nowrap;background:none;border:0;cursor:pointer}
  .mb-seg button[aria-pressed="true"]{background:var(--card);color:var(--text);font-weight:600;box-shadow:0 0 0 1px var(--border)}
  .mb-tbl{width:100%;border-collapse:collapse}
  .mb-tbl th{position:sticky;top:0;background:var(--card);text-align:right;font-size:11px;font-weight:600;color:var(--muted);padding:7px 10px;border-bottom:1px solid var(--border);white-space:nowrap}
  .mb-tbl td{height:32px;padding:0 10px;text-align:right;border-bottom:1px solid var(--border);white-space:nowrap;font-size:12.5px}
  .mb-tbl th:first-child,.mb-tbl td:first-child,.mb-tbl th.l,.mb-tbl td.l{text-align:left}
  .mb-tbl tbody tr[data-mbt]{cursor:pointer}.mb-tbl tbody tr:hover{background:var(--surface-2)}
  .mb-tbl tr:last-child td{border-bottom:0}
  .mb-nm{max-width:150px;overflow:hidden;text-overflow:ellipsis}.mb-nm b{font-weight:600;margin-right:8px}.mb-nm span{color:var(--muted);font-size:12px}
  .mb-sec{color:var(--muted);max-width:96px;overflow:hidden;text-overflow:ellipsis}
  .mb-stack{display:inline-flex;width:54px;height:5px;gap:1px;vertical-align:middle;margin-left:8px}.mb-stack i{display:block;height:100%;border-radius:2px;min-width:2px}
  .mb-f{background:var(--text)}.mb-v{background:var(--muted)}.mb-t{background:var(--accent)}
  .mb-tabs{display:flex;gap:6px;padding:8px 12px;border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:center}
  .mb-tabs button{height:26px;padding:0 12px;border-radius:6px;color:var(--muted);font-size:12px;font-weight:500;background:none;border:0;cursor:pointer}
  .mb-tabs button:hover{background:var(--surface-2)}.mb-tabs button[aria-pressed="true"]{background:var(--accent);color:#fff;font-weight:600}
  .mb-tabs input{margin-left:auto;height:26px;width:170px;max-width:100%;padding:0 8px;border:1px solid var(--border);border-radius:6px;background:var(--surface-2);color:var(--text);font:inherit;font-size:12px}
  .mb-gauge{padding:8px 14px 2px;text-align:center}.mb-gauge svg{width:200px;height:112px}.mb-gauge .l{font-size:14px;font-weight:600;margin-top:-6px}
  .mb-kvr{display:flex;justify-content:space-between;padding:5px 14px;border-top:1px solid var(--border);font-size:12px}.mb-kvr span:first-child{color:var(--muted)}
  .mb-dv{position:relative;display:inline-block;width:80px;height:8px;vertical-align:middle;margin-right:6px}.mb-dv::before{content:"";position:absolute;left:50%;top:-2px;bottom:-2px;width:1px;background:var(--border)}.mb-dv i{position:absolute;top:0;bottom:0;border-radius:1px}
  .mb-ch svg{width:100%;display:block}
  @media(max-width:760px){.mb-tiles.sm .mb-tile:nth-child(n+7){display:none}.mb-s2{grid-column:auto}.mb-hide{display:none}.mb-g{grid-template-columns:minmax(0,1fr)}}
  </style>`;

  const S = { tab: 'cand', q: '', mk: 'K', range: 63, cands: null, spot: null, asked: false };

  function ss() { return (typeof state !== 'undefined' && state.sectorStrength) || null; }
  function stocks() {
    const d = ss(); if (!d) return [];
    return (d.stocks || []).filter((s) => s.cap && s.r && RK.every((k) => s.r[k] != null)).map((s) => ({ t: s.t, n: s.n, g: s.g, cap: s.cap, r: RK.map((k) => s.r[k]) }));
  }
  function flowSeries(market) {
    const mf = state.marketFlows;
    const days = ((mf && mf.markets && mf.markets[market] && mf.markets[market].days) || []).slice().sort((a, b) => a.date.localeCompare(b.date));
    return days.map((d) => { const it = d.items.find((i) => i.name === '외국인'); return it ? { d: d.date, v: Math.round(it.net / 1e8) } : null; }).filter(Boolean);
  }
  function barsSvg(series, H) {
    if (!series.length) return '<span class="mb-dim">자료 없음</span>';
    const W = 400, p = 4, mx = Math.max(...series.map((s) => Math.abs(s.v))) || 1, bw = (W - 2 * p) / series.length, mid = H / 2, up = css('--up'), down = css('--down');
    return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:${H}px" role="img" aria-label="외국인 순매수 일별 막대"><line x1="0" x2="${W}" y1="${mid}" y2="${mid}" stroke="${css('--border')}"/>` +
      series.map((s, i) => { const h = Math.abs(s.v) / mx * (mid - p), y = s.v >= 0 ? mid - h : mid; return `<rect x="${(p + i * bw + 1).toFixed(1)}" y="${y.toFixed(1)}" width="${Math.max(1, bw - 2).toFixed(1)}" height="${Math.max(1, h).toFixed(1)}" fill="${s.v >= 0 ? up : down}"><title>${md(s.d)} ${eok(s.v)}</title></rect>`; }).join('') + '</svg>';
  }
  function lineSvg(series) {
    if (series.length < 2) return '<span class="mb-dim" style="padding:12px;display:block">자료를 불러오는 중이거나 없습니다.</span>';
    const W = 400, H = 170, p = 6, vs = series.map((s) => s.v), lo = Math.min(...vs), hi = Math.max(...vs), pad = (hi - lo) * 0.08 || 1;
    const X = (i) => p + i * (W - 2 * p) / (series.length - 1), Y = (v) => H - p - (v - (lo - pad)) / (hi - lo + 2 * pad) * (H - 2 * p);
    const pts = series.map((s, i) => X(i).toFixed(1) + ',' + Y(s.v).toFixed(1)).join(' '), acc = css('--accent');
    return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:${H}px" role="img" aria-label="코스피200 현물 일별 종가"><polygon points="${p},${H - p} ${pts} ${W - p},${H - p}" fill="${acc}" fill-opacity=".12"/><polyline points="${pts}" fill="none" stroke="${acc}" stroke-width="1.6" vector-effect="non-scaling-stroke"/>` +
      series.map((s, i) => `<circle cx="${X(i).toFixed(1)}" cy="${Y(s.v).toFixed(1)}" r="6" fill="transparent"><title>${md(s.d)} ${fmt(s.v)}</title></circle>`).join('') + '</svg>';
  }
  const tile = (n, s, v, c) => `<div class="mb-tile"><div class="a"><b>${esc(n)}</b><small>${esc(s)}</small></div><div class="v">${v}</div><div>${c}</div></div>`;

  /* ---------- 뼈대 HTML(동적 칸은 mount 가 채운다) ---------- */
  function html() {
    const d = ss(), st = stocks(), N = st.length;
    if (!d || !N) return '';
    const bm = d.benchmark || {}, cb = d.capBenchmark || {}, fK = flowSeries('KOSPI'), fQ = flowSeries('KOSDAQ'), sum5 = (a) => a.slice(-5).reduce((x, y) => x + y.v, 0);
    const upN = st.filter((s) => s.r[0] > 0).length, dnN = st.filter((s) => s.r[0] < 0).length;
    const t1 = [`<div id="mb-t-spot" style="display:contents"></div>`,
      tile('시총가중 1일', '코스피200+코스닥150', `<span class="${cls(cb['1d'])}">${pct(cb['1d'])}</span>`, `<span class="mb-chip">중앙값 ${pct(bm['1d'])}</span>`),
      tile('상승 비율', '1일 · ' + N + '종목', (upN / N * 100).toFixed(1) + '%', `<span class="mb-chip">상승 ${upN} · 하락 ${dnN}</span>`)];
    if (fK.length) t1.push(tile('외국인 코스피', '5일 순매수', `<span class="${cls(sum5(fK))}">${eok(sum5(fK))}</span>`, `<span class="mb-chip ${cls(fK[fK.length - 1].v)}">${md(fK[fK.length - 1].d)} ${eok(fK[fK.length - 1].v)}</span>`));
    if (fQ.length) t1.push(tile('외국인 코스닥', '5일 순매수', `<span class="${cls(sum5(fQ))}">${eok(sum5(fQ))}</span>`, `<span class="mb-chip ${cls(fQ[fQ.length - 1].v)}">${md(fQ[fQ.length - 1].d)} ${eok(fQ[fQ.length - 1].v)}</span>`));
    t1.push(`<div id="mb-t-cand" style="display:contents"></div>`);
    const gs = {}; st.forEach((s) => { const g = (gs[s.g] = gs[s.g] || { n: s.g, cap: 0, w: 0, c: 0 }); g.cap += s.cap; g.w += s.cap * s.r[0]; g.c++; });
    const t2 = Object.values(gs).sort((a, b) => b.cap - a.cap).slice(0, 14).map((g) => tile(g.n, g.c + '종목', fmt(g.cap / 1e12, 1) + '조', chip(g.w / g.cap))).join('');
    const sh = (k) => st.filter((s) => s.r[k] > 0).length / N, r0 = sh(0), th = Math.PI * (1 - r0);
    const gauge = `<svg viewBox="0 0 200 118" role="img" aria-label="상승 종목 비율 ${(r0 * 100).toFixed(1)}%"><defs><linearGradient id="mb-gg"><stop offset="0" style="stop-color:var(--down)"/><stop offset=".5" style="stop-color:var(--surface-3)"/><stop offset="1" style="stop-color:var(--up)"/></linearGradient></defs><path d="M16 104A84 84 0 0 1 184 104" fill="none" stroke="url(#mb-gg)" stroke-width="12" stroke-linecap="round"/><line x1="100" y1="104" x2="${(100 + 66 * Math.cos(th)).toFixed(1)}" y2="${(104 - 66 * Math.sin(th)).toFixed(1)}" stroke="var(--text)" stroke-width="2.5" stroke-linecap="round"/><circle cx="100" cy="104" r="5" fill="var(--text)"/><text x="12" y="116" font-size="10" fill="var(--muted)">약세</text><text x="188" y="116" font-size="10" fill="var(--muted)" text-anchor="end">강세</text></svg><div class="l"><span class="num">${(r0 * 100).toFixed(0)}%</span> ${r0 > .6 ? '강세' : r0 > .4 ? '중립' : '약세'}</div>`;
    const kvr = (a, b) => `<div class="mb-kvr"><span>${a}</span><span class="num">${b}</span></div>`;
    const kvs = kvr('상승 / 하락 (1일)', upN + ' / ' + dnN) + [1, 2, 3, 4].map((k) => kvr('상승 비율 ' + RL[k], (sh(k) * 100).toFixed(0) + '%')).join('') + kvr('시총가중 1일', `<span class="${cls(cb['1d'])}">${pct(cb['1d'])}</span>`) + kvr('유니버스 중앙값 1일', `<span class="${cls(bm['1d'])}">${pct(bm['1d'])}</span>`);
    const lst = (sorted) => '<table class="mb-tbl"><tbody>' + sorted.slice(0, 30).map((s) => `<tr data-mbt="${esc(s.t)}" tabindex="0"><td class="mb-nm l"><b class="num">${esc(s.t)}</b><span>${esc(s.n)}</span></td><td class="num mb-dim">${fmt(s.cap / 1e12, 2)}조</td><td>${chip(s.r[0])}</td></tr>`).join('') + '</tbody></table>';
    const asof = String(d.asOf || '').replace(/\D/g, '').slice(0, 8);
    const TABS = [['gain', '상승 상위'], ['loss', '하락 상위'], ['cap', '시총 순'], ['cand', '후보 점수']];
    return STYLE + `<div class="mb">
      <div class="mb-tiles">${t1.join('')}</div><div class="mb-tiles sm">${t2}</div>
      <div class="mb-g">
        <section class="mb-p"><div class="mb-h"><h2>시장 폭</h2><span class="mb-dim">유니버스 ${N}종목 · 기준 ${esc(md(asof))}</span></div><div class="mb-gauge">${gauge}</div>${kvs}</section>
        <section class="mb-p"><div class="mb-h"><h2>상승 상위 · 1일</h2></div><div class="mb-sc">${lst([...st].sort((a, b) => b.r[0] - a.r[0]))}</div></section>
        <section class="mb-p"><div class="mb-h"><h2>하락 상위 · 1일</h2></div><div class="mb-sc">${lst([...st].sort((a, b) => a.r[0] - b.r[0]))}</div></section>
      </div>
      <div class="mb-g">
        <section class="mb-p mb-ch"><div class="mb-h"><h2>코스피200 현물 · 외국인(코스피)</h2><div class="r"><div class="mb-seg" id="mb-range"><button data-n="21" aria-pressed="${S.range === 21}">1M</button><button data-n="63" aria-pressed="${S.range === 63}">3M</button><button data-n="9999" aria-pressed="${S.range === 9999}">전체</button></div></div></div><div id="mb-line" style="padding:6px 8px 0"></div><div style="padding:0 8px 8px;border-top:1px solid var(--border);margin-top:4px"><div class="mb-dim" style="padding:4px 6px">외국인 순매수 일별(억원) · 최근 ${fK.length}거래일</div>${barsSvg(fK, 70)}</div></section>
        <section class="mb-p mb-s2"><div class="mb-tabs" id="mb-tabs">${TABS.map(([k, l]) => `<button data-k="${k}" aria-pressed="${k === S.tab}">${l}</button>`).join('')}<input id="mb-q" type="search" placeholder="종목·코드·업종 검색" aria-label="종목 검색" value="${esc(S.q)}"></div><div class="mb-sc tall"><table class="mb-tbl" id="mb-mv"></table></div></section>
        <section class="mb-p"><div class="mb-h"><h2>외국인 수급 테이프</h2><div class="r"><div class="mb-seg" id="mb-mk"><button data-m="K" aria-pressed="${S.mk === 'K'}">코스피</button><button data-m="Q" aria-pressed="${S.mk === 'Q'}">코스닥</button></div></div></div><div class="mb-sc tall"><table class="mb-tbl" id="mb-tape"></table></div></section>
      </div>
      <p class="mb-dim" style="margin:0">위 숫자는 코스피200+코스닥150 유니버스 기준이며 코스피·코스닥 지수가 아닙니다. 종목을 누르면 상세가 열립니다.</p></div>`;
  }

  /* ---------- 동적 칸 ---------- */
  function drawTiles() {
    const a = document.getElementById('mb-t-spot'), b = document.getElementById('mb-t-cand');
    if (a) { const sp = S.spot; a.innerHTML = sp && sp.length > 1 ? tile('코스피200', '현물 ' + md(sp[sp.length - 1].d), fmt(sp[sp.length - 1].v), chip(sp[sp.length - 1].v / sp[sp.length - 2].v - 1)) : tile('코스피200', '현물', '…', '<span class="mb-chip">불러오는 중</span>'); }
    if (b) { const c = S.cands; b.innerHTML = c && c.length ? tile('후보 최고점', c[0].n, fmt(c[0].s, 1), `<span class="mb-chip">후보 ${c.length}개</span>`) : tile('후보 최고점', '', '…', '<span class="mb-chip">불러오는 중</span>'); }
  }
  function drawLine() { const el = document.getElementById('mb-line'); if (el) el.innerHTML = lineSvg((S.spot || []).slice(-S.range)); }
  function allRows() {
    const by = {}; stocks().forEach((s) => { by[s.t] = s; });
    (S.cands || []).forEach((c) => { by[c.t] = Object.assign(by[c.t] || { t: c.t, n: c.n }, { score: c.s, conf: c.c, comps: c.comps, flags: c.flags }); });
    return Object.values(by);
  }
  function drawMv() {
    const el = document.getElementById('mb-mv'); if (!el) return;
    const all = allRows(), s = S.q.trim().toLowerCase();
    const T = { gain: () => all.filter((x) => x.r).sort((a, b) => b.r[0] - a.r[0]), loss: () => all.filter((x) => x.r).sort((a, b) => a.r[0] - b.r[0]), cap: () => all.filter((x) => x.cap).sort((a, b) => b.cap - a.cap), cand: () => all.filter((x) => x.score != null).sort((a, b) => b.score - a.score) };
    let rows = T[S.tab](); if (s) rows = all.filter((x) => (x.n + x.t + (x.g || '')).toLowerCase().includes(s)).sort((a, b) => (b.cap || 0) - (a.cap || 0));
    rows = rows.slice(0, s ? 80 : 40);
    const cell = (r, hide) => r == null ? `<td class="mb-dim${hide ? ' mb-hide' : ''}">—</td>` : `<td class="num ${cls(r)}${hide ? ' mb-hide' : ''}">${pct(r)}</td>`;
    el.innerHTML = '<thead><tr><th>#</th><th class="l">종목</th><th class="l mb-hide">업종</th><th>1일</th><th>1주</th><th class="mb-hide">1개월</th><th class="mb-hide">시총</th><th>점수</th></tr></thead><tbody>' +
      (rows.length ? rows.map((x, i) => { const r = x.r || [], tot = x.comps ? (x.comps[0] + x.comps[1] + x.comps[2]) || 1 : 1, w = (v) => (v / tot * 100).toFixed(0);
        return `<tr data-mbt="${esc(x.t)}" tabindex="0"><td class="num mb-dim">${i + 1}</td><td class="mb-nm l"><b class="num">${esc(x.t)}</b><span>${esc(x.n)}</span></td><td class="mb-sec l mb-hide">${esc(x.g || '—')}</td>${cell(r[0])}${cell(r[1])}${cell(r[2], true)}<td class="num mb-dim mb-hide">${x.cap ? fmt(x.cap / 1e12, 2) + '조' : '—'}</td>` +
          `<td class="num">${x.score != null ? `<b>${fmt(x.score, 1)}</b><span class="mb-stack" title="재무 ${x.comps[0]} · 가치 ${x.comps[1]} · 기술 ${x.comps[2]}"><i class="mb-f" style="width:${w(x.comps[0])}%"></i><i class="mb-v" style="width:${w(x.comps[1])}%"></i><i class="mb-t" style="width:${w(x.comps[2])}%"></i></span>` : '<span class="mb-dim">—</span>'}</td></tr>`; }).join('')
        : `<tr><td colspan="8" class="mb-dim" style="text-align:center;height:56px">${S.tab === 'cand' && !S.cands ? '후보 자료를 불러오는 중…' : '결과 없음'}</td></tr>`) + '</tbody>';
  }
  function drawTape() {
    const el = document.getElementById('mb-tape'); if (!el) return;
    const f = flowSeries(S.mk === 'K' ? 'KOSPI' : 'KOSDAQ'), mx = Math.max(1, ...f.map((x) => Math.abs(x.v))), up = css('--up'), down = css('--down');
    const rows = f.map((x, i) => ({ ...x, s5: f.slice(Math.max(0, i - 4), i + 1).reduce((a, y) => a + y.v, 0) })).reverse();
    el.innerHTML = '<thead><tr><th>일자</th><th class="l">순매수(억)</th><th>5일합</th></tr></thead><tbody>' + (rows.map((x) => `<tr><td class="num">${md(x.d)}</td><td class="l"><span class="mb-dv"><i style="${x.v >= 0 ? 'left:50%' : 'right:50%'};width:${(Math.abs(x.v) / mx * 50).toFixed(1)}%;background:${x.v >= 0 ? up : down}"></i></span><span class="num ${cls(x.v)}">${eok(x.v).replace('억', '')}</span></td><td class="num ${cls(x.s5)}">${eok(x.s5).replace('억', '')}</td></tr>`).join('') || '<tr><td colspan="3" class="mb-dim">자료 없음</td></tr>') + '</tbody>';
  }
  function drawAll() { drawTiles(); drawLine(); drawMv(); drawTape(); }

  function loadLazy() {
    if (S.asked) return; S.asked = true;
    loadJson('kospi200fut_history').then((x) => { S.spot = Array.isArray(x) ? x.filter((r) => r.spot != null).map((r) => ({ d: r.date, v: r.spot })) : []; drawAll(); });
    loadJson('latest-v2').then((lv) => {
      const c = [];
      if (lv && lv.results) lv.results.map((x) => x.result).filter((r) => r.finalScore != null && r.tradeAllowed && ((r.confidence && r.confidence.value) || 0) >= 80)
        .sort((a, b) => b.finalScore - a.finalScore).slice(0, 8).forEach((r) => c.push({ t: r.ticker, n: r.name, s: r.finalScore, c: r.confidence.value, comps: ['fundamental', 'valuation', 'technical', 'supplyDemand'].map((k) => (r.components || {})[k] || 0), flags: (r.flags || []).map(String).slice(0, 2) }));
      S.cands = c; drawAll();
    });
  }

  function mount() {
    const root = document.querySelector('#content .mb'); if (!root) return;
    drawAll(); loadLazy();
    const seg = (id, fn) => { const e = root.querySelector(id); if (e) e.addEventListener('click', (ev) => { const b = ev.target.closest('button'); if (!b) return; e.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b)); fn(b); }); };
    seg('#mb-range', (b) => { S.range = +b.dataset.n; drawLine(); }); seg('#mb-mk', (b) => { S.mk = b.dataset.m; drawTape(); });
    seg('#mb-tabs', (b) => { if (b.dataset.k) { S.tab = b.dataset.k; S.q = ''; const q = document.getElementById('mb-q'); if (q) q.value = ''; drawMv(); } });
    const q = document.getElementById('mb-q'); if (q) q.addEventListener('input', (e) => { S.q = e.target.value; drawMv(); });
    const open = (el) => { const t = el && el.dataset.mbt; if (!t) return; const r = allRows().find((x) => x.t === t); openStockDetail(t, r ? r.n : t); };
    root.addEventListener('click', (e) => open(e.target.closest('[data-mbt]')));
    root.addEventListener('keydown', (e) => { if (e.key === 'Enter') open(e.target.closest('tr[data-mbt]')); });
  }

  window.MktBoard = { html, mount };
})();
