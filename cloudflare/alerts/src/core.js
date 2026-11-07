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
