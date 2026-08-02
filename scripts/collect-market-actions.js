'use strict';
/**
 * TASK-2B: 현재 시장조치(관리종목·거래정지·투자주의환기) 스냅샷 수집기
 * 읽기 전용. data/state/, data/state-history/ 에 일절 접근하지 않는다.
 */
const https = require('https');
const fs = require('fs');
const path = require('path');

const OUT_DIR = path.join(__dirname, '..', 'data', 'goldenset');
const OUT_JSON = path.join(OUT_DIR, 'market-actions-snapshot.json');

// 밀리초 제거 — 인수조건 정규식과 일치시킨다
const kstNow = () => new Date(Date.now() + 9 * 3600000).toISOString().replace(/\.\d{3}Z$/, '+09:00');

// URL 미검증. 후보를 순서대로 시도하고 성공한 것을 meta.sources 에 기록한다.
const SOURCES = {
  management: [
    'https://finance.naver.com/sise/management.naver',
    'https://finance.naver.com/sise/item_manage.naver',
  ],
  tradingHalt: [
    'https://finance.naver.com/sise/trading_halt.naver',
    'https://finance.naver.com/sise/sise_trading_halt.naver',
  ],
  investmentWarning: [
    'https://finance.naver.com/sise/investment_alert.naver?type=caution',
    'https://finance.naver.com/sise/investment_risk.naver',
  ],
};

function fetchBuf(url, redirects = 0) {
  return new Promise((resolve, reject) => {
    https.get(url, { headers: { 'User-Agent': 'Mozilla/5.0' } }, (res) => {
      if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location && redirects < 3) {
        res.resume();
        return resolve(fetchBuf(new URL(res.headers.location, url).toString(), redirects + 1));
      }
      // 상태코드 검사 — 없으면 404 본문이 "정상 수집 0건"으로 둔갑한다
      if (res.statusCode !== 200) { res.resume(); return reject(new Error(`HTTP ${res.statusCode} @ ${url}`)); }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));      // Buffer 누적. 문자열 누적 금지(멀티바이트 절단)
      res.on('end', () => resolve(Buffer.concat(chunks)));
    }).on('error', reject);
  });
}

function decodeEucKr(buf) {
  try { return new TextDecoder('euc-kr').decode(buf); }   // Node 18+ full-icu
  catch { return buf.toString('latin1'); }                // 실패는 한글 정합성 검사에서 잡힌다
}

function parseRows(html) {
  const out = [];
  for (const row of html.split(/<tr[\s>]/i)) {
    const m = row.match(/\/item\/main\.naver\?code=(\d{6})[^>]*>([^<]+)</);
    if (!m) continue;
    
    const cells = [...row.matchAll(/<td[^>]*>([\s\S]*?)<\/td>/gi)]
      .map((c) => c[1].replace(/<[^>]*>/g, '').replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim())
      .filter(Boolean);
    const name = m[2].trim();
    
    const PRICE = /^[\d,.\-+%]+$/;
    const DIRECTION = /^(상승|하락|보합)/;   
    const rawReason = cells.find((c) => c !== name && !PRICE.test(c) && !DIRECTION.test(c)) || null;
    // 네이버 표는 동일 문구를 2회 반복해 담는다("시가총액 미달 시가총액 미달") — 정규화
    const reason = rawReason ? rawReason.replace(/^(.+?)\s*\1$/, '$1') : null;
    
    const DATE_RE = /(\d{4})[.\-/](\d{2})[.\-/](\d{2})/;   
    const dateMatch = cells.map((c) => c.match(DATE_RE)).find(Boolean);
    const at = dateMatch ? `${dateMatch[1]}-${dateMatch[2]}-${dateMatch[3]}` : null;
    
    // 진단 임시 필드 _rawCells 추가
    out.push({ ticker: m[1], name, reason, at, _rawCells: cells });
  }
  const seen = new Set();
  return out.filter((r) => !seen.has(r.ticker) && seen.add(r.ticker));
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const out = {
    meta: { collectedAt: kstNow(), sources: [] },
    management: [], tradingHalt: [], investmentWarning: [],
    _diagnostics: { failed: [] },
  };
  const DATE_KEY = { management: 'designatedAt', tradingHalt: 'haltedAt', investmentWarning: 'designatedAt' };

  for (const [kind, urls] of Object.entries(SOURCES)) {
    let done = false;
    for (const url of urls) {
      try {
        const rows = parseRows(decodeEucKr(await fetchBuf(url)));
        if (rows.length === 0) throw new Error('0 rows parsed (구조 변경 또는 잘못된 URL)');
        
        out[kind] = rows.map((r) => ({ ticker: r.ticker, name: r.name, reason: r.reason, [DATE_KEY[kind]]: r.at }));
        
        // 진단: 한글깨짐/날짜결측 표본 3건만 원본 셀과 함께 별도 기록 (프로덕션 스키마 오염 안 시킴)
        out._diagnostics[`${kind}RawSample`] = rows
          .filter((r) => !NAME_CHARSET.test(r.name || ''))
          .slice(0, 3)
          .map((r) => ({ ticker: r.ticker, name: r.name, cells: r._rawCells }));

        out.meta.sources.push({ kind, url, method: 'html', count: rows.length });
        done = true; break;
      } catch (e) {
        out._diagnostics.failed.push({ kind, url, reason: e.message });   // fail-soft: 다음 후보로
      }
      await new Promise((r) => setTimeout(r, 300));
    }
    if (!done) console.error(`[WARN] ${kind}: 모든 후보 URL 실패`);
  }

  fs.writeFileSync(OUT_JSON, JSON.stringify(out, null, 2), 'utf8');
  console.log(`saved ${OUT_JSON} (${fs.statSync(OUT_JSON).size} bytes)`);
  process.exit(runTests(out) ? 0 : 1);
}

// 정상 종목명에 나올 수 있는 문자: ASCII + 한글 음절/자모.
// 그 밖(U+0080~U+00FF latin1 폴백, U+FFFD)은 EUC-KR 디코딩 실패의 흔적이다.
const NAME_CHARSET = /^[\x20-\x7E\uAC00-\uD7A3\u3131-\u318E]+$/;

function runTests(out) {
  let ok = true;
  const chk = (c, m) => { console.log(`${c ? '[PASS]' : '[FAIL]'} ${m}`); if (!c) ok = false; };
  const all = [...out.management, ...out.tradingHalt, ...out.investmentWarning];

  chk(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+09:00$/.test(out.meta.collectedAt), 'collectedAt KST 형식');
  chk(all.every((i) => /^\d{6}$/.test(i.ticker)), 'ticker 6자리 숫자');
  for (const k of ['management', 'tradingHalt', 'investmentWarning']) {
    const t = out[k].map((i) => i.ticker);
    chk(new Set(t).size === t.length, `${k} ticker 중복 없음 (${t.length}건)`);
  }
  
  // 치명 실패 모드는 "한글이 없다"가 아니라 "EUC-KR 디코딩이 깨졌다"이다.
  // ① 문자셋 검사 — SHD·STX·EDGC·DXVX 같은 정상 영문 사명은 통과해야 한다.
  const garbled = all.filter((i) => !NAME_CHARSET.test(i.name || ''));
  chk(garbled.length === 0, `종목명 인코딩 정합성 (위반 ${garbled.length}건${garbled.length ? ' 예: ' + garbled[0].name : ''})`);
  // ② 비율 검사 — '?' 치환처럼 ASCII로 떨어지는 실패는 ①을 통과하므로 전체 한글 비율로 잡는다.
  const hangul = all.filter((i) => /[\uAC00-\uD7A3]/.test(i.name || '')).length;
  const ratio = all.length ? hangul / all.length : 0;
  chk(ratio >= 0.7, `종목명 한글 비율 ${(ratio * 100).toFixed(1)}% ≥ 70% (${hangul}/${all.length})`);
  chk(out.management.length > 0, `management 수집 건수 > 0 (${out.management.length}건)`);
  chk(out.meta.sources.length > 0, 'meta.sources 기록됨');
  
  // 이번 세션에서 실측된 오염 패턴 회귀 방지
  const dirLeak = all.filter((i) => /^(상승|하락|보합)/.test(i.reason || ''));
  chk(dirLeak.length === 0, `reason 필드에 등락방향 오염 없음 (위반 ${dirLeak.length}건)`);
  
  // 날짜 컬럼이 실제로 있는 두 타입만 결측을 게이트로 삼는다 (P4 시딩의 activatedAt 원천).
  for (const [k, key] of [['management', 'designatedAt'], ['tradingHalt', 'haltedAt']]) {
    const miss = out[k].filter((i) => !i[key]);
    chk(miss.length === 0, `${k} ${key} 결측 없음 (위반 ${miss.length}/${out[k].length}건)`);
  }
  // investmentWarning은 소스에 지정일자 컬럼 자체가 없다. 전건 null이 정상이고, 값이 생기면 구조 변경 신호.
  const iw = out.investmentWarning;
  chk(iw.every((i) => i.designatedAt === null),
      `investmentWarning designatedAt 전건 null (소스에 지정일자 컬럼 없음, ${iw.length}건)`);
  return ok;
}

main().catch((e) => { console.error(e); process.exit(1); });
