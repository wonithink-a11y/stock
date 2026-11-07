// 알림 핵심 로직(순수 함수) — scripts/vix-signal-alert.py · vix-inverse-check.py · price-target-alert.py 의 JS 이식.
// 파이썬 쪽이 정본이다. 바꾸면 test/parity.mjs 로 두 구현의 결과가 같은지 다시 본다.

export const ENTRY = 20, EXIT = 16, LEVELS = [20, 25, 30, 35];

export function step([holding, n], v) {
  const cnt = LEVELS.filter((L) => L <= v).length;
  if (holding && v <= EXIT) return [[false, 0], 'EXIT'];
  if (!holding && v >= ENTRY) return [[true, cnt], 'ENTER'];
  if (holding) { const m = Math.max(n, cnt); return [[true, m], m > n ? 'ADD' : 'HOLD']; }
  return [[false, 0], 'WAIT'];
}

/** closes=[[날짜, 종가]] 오름차순. 처음 VIX ≤ 16 인 날부터 시작. 그런 날이 없으면 null. */
export function run(closes) {
  const i0 = closes.findIndex(([, v]) => v <= EXIT);
  if (i0 < 0) return null;
  let state = [false, 0], sig = 'WAIT';
  for (const [, v] of closes.slice(i0)) [state, sig] = step(state, v);
  const [d, v] = closes[closes.length - 1];
  return { n: state[1], sig, date: d, vix: v };
}

export function vixMessage(sig, n, d, v) {
  const head = `VIX 종가 ${v.toFixed(2)} (${d})`;
  if (sig === 'ENTER') return `[SVIX 매수] ${head}\n매수 구간 진입 — 오늘 미국 장 초반 1/4 칸부터(누적 ${n}/${LEVELS.length}칸). 지정가는 시세 +0.5%.`;
  if (sig === 'ADD') return `[SVIX 추가매수] ${head}\n분할 단계 ${n}/${LEVELS.length} — 오늘 장 초반 추가 1/4 칸. 지정가는 시세 +0.5%.`;
  return `[SVIX 전량 매도] ${head}\n16 이하 마감 — 오늘 장 초반 전량 매도. 지정가는 시세 −0.5%.`;
}

/** 알릴 메시지와 새 lastSent. 신호가 ENTER/ADD/EXIT 이고 그 날짜를 아직 안 보냈을 때만. */
export function vixAlert(closes, lastSent) {
  const r = run(closes);
  if (r && ['ENTER', 'ADD', 'EXIT'].includes(r.sig) && r.date !== lastSent) {
    return { msg: vixMessage(r.sig, r.n, r.date, r.vix), date: r.date };
  }
  return null;
}

// ---- 시각 ----
function parts(now, timeZone) {
  const f = new Intl.DateTimeFormat('en-US', { timeZone, hour12: false, weekday: 'short', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
  const o = Object.fromEntries(f.formatToParts(now).map((p) => [p.type, p.value]));
  const hh = Number(o.hour) % 24;
  return { wd: o.weekday, ymd: `${o.year}${o.month}${o.day}`, iso: `${o.year}-${o.month}-${o.day}`, min: hh * 60 + Number(o.minute) };
}
export const etDate = (now) => parts(now, 'America/New_York').iso;

export function marketOpen(market, now) {
  const t = parts(now, market === 'KR' ? 'Asia/Seoul' : 'America/New_York');
  if (t.wd === 'Sat' || t.wd === 'Sun') return false;
  return market === 'KR' ? t.min >= 9 * 60 && t.min <= 15 * 60 + 30 : t.min >= 9 * 60 + 30 && t.min <= 16 * 60;
}

// ---- 가격 목표 ----
export const tid = (t) => `${t.market}:${t.symbol}:${t.dir}:${t.price}`;
export const hit = (t, px) => (t.dir === 'above' ? px >= t.price : px <= t.price);

export function priceMessage(t, px) {
  const word = t.dir === 'above' ? '이상 도달' : '이하 도달';
  const unit = t.market === 'KR' ? '원' : '달러';
  const f = (x) => x.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return `[가격 목표] ${t.symbol} ${f(t.price)}${unit} ${word} — 현재 ${f(px)}` + (t.note ? `\n${t.note}` : '');
}

/** 네이버 fchart XML 에서 오늘(KST) 봉의 종가. 휴장일의 직전 봉이면 null. */
export function parseNaver(xml, now) {
  const rows = [...xml.matchAll(/<item data="([^"]+)"/g)].map((m) => m[1].split('|'));
  if (!rows.length) return null;
  const last = rows[rows.length - 1];
  return last[0] === parts(now, 'Asia/Seoul').ymd ? Number(last[4]) : null;
}

/** 네이버 fchart XML 의 오늘(KST) 봉 {px, prev}(전일 종가). 휴장일(오늘 봉 없음)이면 null. */
export function parseNaverQuote(xml, now) {
  const rows = [...xml.matchAll(/<item data="([^"]+)"/g)].map((m) => m[1].split('|'));
  if (rows.length < 2) return null;
  const last = rows[rows.length - 1];
  return last[0] === parts(now, 'Asia/Seoul').ymd ? { px: Number(last[4]), prev: Number(rows[rows.length - 2][4]) } : null;
}

// ---- 등락률 알림(SVIX·SOXL 같은 소수 종목) — 하루 한 번씩 단계(STEP %)를 새로 넘거나 방향이 바뀔 때만 ----
export const MOVE_STEP = 10;
export const pctChange = (px, prev) => Math.round(((px / prev) - 1) * 100 * 1e6) / 1e6;   // 부동소수 오차로 정확히 −10% 가 −9.99…가 되지 않게
export const moveLevel = (pct, step = MOVE_STEP) => Math.sign(pct) * Math.floor(Math.abs(pct) / step) || 0;   // -0 → 0

const fmt = (x, d = 2) => x.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
const sgn = (x) => (x >= 0 ? '+' : '−') + fmt(Math.abs(x)) + '%';

/** quotes=[{symbol, px, prev}], state={date, levels} → {alerts:[메시지], state}. dateKey 가 바뀌면 단계를 비운다. */
export function checkMoves(quotes, state, dateKey, step = MOVE_STEP) {
  const st = state && state.date === dateKey ? { date: dateKey, levels: { ...state.levels } } : { date: dateKey, levels: {} };
  const alerts = [];
  for (const q of quotes) {
    const pct = pctChange(q.px, q.prev), lvl = moveLevel(pct, step), last = st.levels[q.symbol] || 0;
    if (lvl !== 0 && (Math.sign(lvl) !== Math.sign(last) || Math.abs(lvl) > Math.abs(last))) {
      alerts.push(`[급등락] ${q.symbol} ${sgn(pct)} — 현재 ${fmt(q.px)} (전일 종가 ${fmt(q.prev)})\n전일 종가 대비 ${Math.abs(lvl) * step}% 단계${lvl < 0 ? ' 하락' : ' 상승'}`);
      st.levels[q.symbol] = lvl;
    }
  }
  return { alerts, state: st };
}

// ---- 장중 VIX 단계(20·25·30·35…, 5 단위) — 참고용. 매매 신호는 여전히 마감 종가 기준(vixAlert) ----
export const vixLevel = (v) => (v >= 20 ? Math.floor(v / 5) * 5 : 0);

/** 오늘 처음 '전일 종가의 단계'보다 높은 단계에 닿았을 때만(이미 높은 구간에 있는 날마다 반복해서 울리지 않게). state={date, level} → {msg|null, state} */
export function checkVixLevel(px, prev, state, dateKey) {
  const st = state && state.date === dateKey ? { ...state } : { date: dateKey, level: 0 };
  const lvl = vixLevel(px), base = Math.max(vixLevel(prev), st.level);
  if (lvl > base) {
    st.level = lvl;
    return { msg: `[VIX 장중] VIX ${fmt(px)} — ${lvl} 단계 도달 (전일 종가 ${fmt(prev)})\n참고용 장중 값입니다. SVIX 매매 신호는 마감 종가 기준이라 마감 뒤 07:10 에 따로 옵니다.`, state: st };
  }
  st.level = Math.max(st.level, lvl);
  return { msg: null, state: st };
}

/** 마감 요약 한 통. rows=[{label, px, prev}] */
export function digestMessage(title, dateLabel, rows) {
  return `[${title}] ${dateLabel}\n` + rows.map((r) => `${r.label} ${fmt(r.px)} (${sgn(pctChange(r.px, r.prev))})`).join('\n');
}

/** 장이 열려 있고 아직 안 울린 목표 중 도달한 것. fetchPx(market, symbol) → 가격|null */
export async function checkTargets(targets, fired, now, fetchPx) {
  const out = [];
  for (const t of targets) {
    if (fired.has(tid(t)) || !marketOpen(t.market, now)) continue;
    const px = await fetchPx(t.market, t.symbol);
    if (px != null && hit(t, px)) out.push({ id: tid(t), msg: priceMessage(t, px) });
  }
  return out;
}
