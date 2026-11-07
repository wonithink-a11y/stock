// JS 이식(core.js)이 파이썬 정본(scripts/vix-signal-alert.py · price-target-alert.py)과 같은 결과를 내는지 본다.
//   node cloudflare/alerts/test/parity.mjs     (저장소 루트에서, python 필요 · 네트워크 불필요)
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { vixAlert, marketOpen, priceMessage, parseNaver } from '../src/core.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const py = (code, input) => JSON.parse(execFileSync('python', ['-X', 'utf8', '-c', code], { cwd: ROOT, input: JSON.stringify(input), encoding: 'utf8', env: { ...process.env, PYTHONIOENCODING: 'utf-8' } }));

const PRE = `
import sys, json, importlib.util, datetime as dt
def load(n, f):
    s = importlib.util.spec_from_file_location(n, 'scripts/' + f); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
vs = load('vs', 'vix-signal-alert.py'); pt = load('pt', 'price-target-alert.py')
inp = json.load(sys.stdin)
`;
let fails = 0, count = 0;
const eq = (name, a, b) => { count++; if (JSON.stringify(a) !== JSON.stringify(b)) { fails++; console.log('FAIL', name, '\n  js:', JSON.stringify(a), '\n  py:', JSON.stringify(b)); } };

// 1) VIX 신호: 무작위 종가열 400개 — 마지막 값 기준 신호·메시지·날짜가 같아야 한다
let seed = 12345; const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
const cases = [];
for (let c = 0; c < 400; c++) {
  const n = 5 + Math.floor(rnd() * 40); let v = 14 + rnd() * 10; const closes = [];
  for (let i = 0; i < n; i++) { v = Math.max(9, Math.min(60, v + (rnd() - 0.48) * 6)); closes.push([new Date(Date.UTC(2024, 0, 1 + i)).toISOString().slice(0, 10), Math.round(v * 100) / 100]); }
  for (let k = 5; k <= n; k++) {                      // 모든 앞부분(prefix)이 각각 하나의 시험 — 마지막 날에 신호가 나는 경우를 넉넉히 만든다
    const cl = closes.slice(0, k);
    cases.push({ closes: cl, last: rnd() < 0.3 ? cl[cl.length - 1][0] : '' });
  }
}
const pyVix = py(PRE + `
out = []
for c in inp:
    cl = [(dt.date.fromisoformat(d), v) for d, v in c['closes']]
    try:
        r = vs.check(cl, c['last'])
        out.append(None if r[0] is None else [r[0], r[1]])
    except SystemExit:
        out.append(None)
print(json.dumps(out, ensure_ascii=False))
`, cases);
cases.forEach((c, i) => { const j = vixAlert(c.closes, c.last); eq(`vix#${i}`, j ? [j.msg, j.date] : null, pyVix[i]); });
const nAlert = pyVix.filter(Boolean).length; console.log("신호가 나온 시험 수:", nAlert, "/", pyVix.length);
eq('시험이 신호를 충분히 다룬다(매수·추가·매도 모두)', [nAlert >= 100, ['[SVIX 매수]', '[SVIX 추가매수]', '[SVIX 전량 매도]'].every((k) => pyVix.some((r) => r && r[0].startsWith(k)))], [true, true]);

// 2) 장 시간: 일주일을 17분 간격으로 — KR/US 열림 여부가 같아야 한다
const times = []; for (let m = 0; m < 7 * 24 * 60; m += 17) times.push(Date.UTC(2026, 10, 9) / 1000 + m * 60);   // 2026-11-09(월) 00:00 UTC 부터
const pyMk = py(PRE + `
out = []
for t in inp:
    n = dt.datetime.fromtimestamp(t, dt.timezone.utc)
    out.append([pt.market_open('KR', n), pt.market_open('US', n)])
print(json.dumps(out))
`, times);
times.forEach((t, i) => eq(`mkt#${i}`, [marketOpen('KR', new Date(t * 1000)), marketOpen('US', new Date(t * 1000))], pyMk[i]));

// 3) 가격 메시지·네이버 파싱
const tg = [{ market: 'KR', symbol: '005930', dir: 'above', price: 85000, note: '돌파' }, { market: 'US', symbol: 'NVDA', dir: 'below', price: 170.5 }];
const pyMsg = py(PRE + `print(json.dumps([pt.message(t, 86123.456) for t in inp], ensure_ascii=False))`, tg);
tg.forEach((t, i) => eq(`msg#${i}`, priceMessage(t, 86123.456), pyMsg[i]));
const xml = '<item data="20261106|180000|196500|179200|193500|35068743" />\n<item data="20261109|193500|195000|190000|191250|100" />';
eq('naver today', parseNaver(xml, new Date('2026-11-09T01:00:00Z')), 191250);
eq('naver holiday', parseNaver(xml, new Date('2026-11-10T01:00:00Z')), null);

console.log(fails ? `FAIL ${fails}/${count}` : `OK ${count}/${count}`);
process.exit(fails ? 1 : 0);
