/**
 * add-ticker.js (v1.0)
 *
 * config/watchlist.json 에 관심종목을 추가합니다. GitHub Actions 의 add-ticker 워크플로에서
 * 종목코드만 입력하면 실행되므로, 휴대폰에서도 JSON 을 직접 편집하지 않고 종목을 늘릴 수 있습니다.
 *
 * 하는 일
 *  1) 종목명 자동 조회  — KR: 네이버, US: Yahoo search
 *  2) 실제 시세 검증    — 일봉이 실제로 받아지는지 확인 (collect.js와 같은 소스)
 *     ★ 이게 핵심입니다. 오타 티커를 그냥 추가하면 대시보드에 이름만 뜨고 데이터가 없는 행이
 *       조용히 생깁니다(원인 찾기 어려움). 검증에 실패한 코드는 추가하지 않습니다.
 *  3) 중복 제거 후 추가 + groups/groupLabels 정리
 *  4) universeVersion 갱신 + manualAdditions 이력 기록
 *     백테스트 연속성 규칙 때문입니다 — 유니버스가 언제 어떻게 바뀌었는지 남겨야
 *     "이 성과가 어떤 종목 집합에서 나온 것인가"를 나중에 복원할 수 있습니다.
 *
 * 사용법
 *   node scripts/add-ticker.js --market KR --codes "042700,000660"
 *   node scripts/add-ticker.js --market US --codes "AMZN, META" --groups "watch-manual,us-core"
 *   node scripts/add-ticker.js --market KR --codes 042700 --name 한미반도체   # 이름 직접 지정
 *   node scripts/add-ticker.js --market US --codes AMZN --dry-run            # 저장 안 함
 *   node scripts/add-ticker.js --market US --codes AMZN --no-verify          # 시세 검증 생략
 *
 * 추가 후
 *   재무는 별도 배치가 채웁니다. KR → quarterly-fundamentals, US → fundamentals-us 워크플로.
 *   점수는 다음 daily-analysis(평일 16:40 KST) 실행에 반영됩니다. 급하면 수동 실행하세요.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const WATCHLIST_PATH = path.join(ROOT, 'config', 'watchlist.json');

const UA = { 'User-Agent': 'Mozilla/5.0 (compatible; stock-scoring-app)' };
const YAHOO_UA = {
  'User-Agent':
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
  Accept: 'application/json',
};
const TIMEOUT_MS = 15000;

// ---------- 인자 파싱 ----------

function parseArgs(argv) {
  const out = { market: 'KR', codes: '', groups: 'watch-manual', name: '', dryRun: false, verify: true };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--market') out.market = String(argv[++i] || '').toUpperCase();
    else if (a === '--codes') out.codes = argv[++i] || '';
    else if (a === '--groups') out.groups = argv[++i] || '';
    else if (a === '--name') out.name = argv[++i] || '';
    else if (a === '--dry-run') out.dryRun = true;
    else if (a === '--no-verify') out.verify = false;
  }
  return out;
}

function splitList(s) {
  return String(s || '')
    .split(/[,\s]+/)
    .map((v) => v.trim())
    .filter(Boolean);
}

/** KR 6자리 코드는 앞자리 0이 사라지기 쉬워(엑셀·숫자 입력) 6자리로 복원합니다. */
function normalizeCode(code, market) {
  const c = String(code).trim();
  if (market === 'US') return c.toUpperCase().replace(/\./g, '-'); // BRK.B → BRK-B
  return /^\d+$/.test(c) ? c.padStart(6, '0') : c.toUpperCase();
}

// ---------- fetch ----------

async function fetchOnce(url, headers = UA) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, { headers, signal: controller.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res;
  } finally {
    clearTimeout(timer);
  }
}

const getJson = async (url, headers) => (await fetchOnce(url, headers)).json();
const getText = async (url, headers) => (await fetchOnce(url, headers)).text();

// ---------- 종목명 조회 ----------

async function resolveNameKR(code) {
  try {
    const d = await getJson(`https://m.stock.naver.com/api/stock/${code}/integration`);
    const n = d.stockName || d.stockNameEng || (d.stockItem && d.stockItem.stockName);
    if (n) return String(n).trim();
  } catch (e) {
    /* 다음 소스 시도 */
  }
  try {
    const d = await getJson(`https://m.stock.naver.com/api/stock/${code}/basic`);
    if (d.stockName) return String(d.stockName).trim();
  } catch (e) {
    /* 실패 시 null */
  }
  return null;
}

async function resolveNameUS(ticker) {
  try {
    const d = await getJson(
      `https://query1.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(ticker)}&quotesCount=5&newsCount=0`,
      YAHOO_UA
    );
    const hit = (d.quotes || []).find((q) => String(q.symbol).toUpperCase() === ticker.toUpperCase());
    const q = hit || (d.quotes || [])[0];
    if (q) {
      // Yahoo 는 영문 정식명("Amazon.com, Inc.")을 줍니다. 대시보드 표가 좁아 법인 접미사를 떼어냅니다.
      // 한글 종목명을 쓰려면 --name(워크플로의 '종목명' 입력)으로 직접 지정하세요.
      return String(q.shortname || q.longname || q.symbol)
        .replace(/,?\s+(Inc|Incorporated|Corp|Corporation|Company|Co|plc|PLC|Ltd|Limited|Holdings|Group|N\.V|S\.A)\.?$/i, '')
        .replace(/\s+$/, '')
        .trim();
    }
  } catch (e) {
    /* 실패 시 null */
  }
  return null;
}

// ---------- 시세 검증 (collect.js 와 같은 소스) ----------

async function verifyKR(code) {
  const xml = await getText(
    `https://fchart.stock.naver.com/sise.nhn?symbol=${code}&timeframe=day&count=5&requestType=0`
  );
  const m = xml.match(/<item data="([^"]+)"\s*\/>/);
  if (!m) throw new Error('네이버 일봉 없음 (상장폐지·코드 오타 가능)');
  const parts = m[1].split('|');
  return { lastDate: parts[0], close: Number(parts[4]) };
}

async function verifyUS(ticker) {
  const json = await getJson(
    `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?range=5d&interval=1d`,
    YAHOO_UA
  );
  const r = json && json.chart && json.chart.result && json.chart.result[0];
  if (!r || !Array.isArray(r.timestamp) || r.timestamp.length === 0) {
    const msg = (json && json.chart && json.chart.error && json.chart.error.description) || '데이터 없음';
    throw new Error(`Yahoo 일봉 없음: ${msg}`);
  }
  const q = (r.indicators && r.indicators.quote && r.indicators.quote[0]) || {};
  const closes = (q.close || []).filter((v) => v !== null && v !== undefined);
  const d = new Date(r.timestamp[r.timestamp.length - 1] * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return {
    lastDate: `${d.getUTCFullYear()}${pad(d.getUTCMonth() + 1)}${pad(d.getUTCDate())}`,
    close: closes[closes.length - 1] ?? null,
  };
}

// ---------- 메인 ----------

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!['KR', 'US'].includes(args.market)) {
    console.error(`market 은 KR 또는 US 여야 합니다 (입력: ${args.market})`);
    process.exit(1);
  }
  const codes = splitList(args.codes).map((c) => normalizeCode(c, args.market));
  if (codes.length === 0) {
    console.error('--codes 가 비어 있습니다.');
    process.exit(1);
  }
  if (args.name && codes.length > 1) {
    console.error('--name 은 종목 1개일 때만 쓸 수 있습니다.');
    process.exit(1);
  }

  const groups = splitList(args.groups);
  const wl = JSON.parse(fs.readFileSync(WATCHLIST_PATH, 'utf-8'));
  wl.tickers = wl.tickers || [];
  const existing = new Set(wl.tickers.map((t) => String(t.code).toUpperCase()));

  console.log(`추가 요청: ${args.market} ${codes.join(', ')} (그룹: ${groups.join(', ') || '없음'})`);
  console.log(`시세 검증: ${args.verify ? 'on' : 'off'}\n`);

  const added = [];
  const skipped = [];
  const failed = [];

  for (const code of codes) {
    if (existing.has(code.toUpperCase())) {
      // 이미 있는 종목이면 그룹만 합쳐줍니다(중복 엔트리를 만들지 않음).
      const t = wl.tickers.find((x) => String(x.code).toUpperCase() === code.toUpperCase());
      const before = (t.groups || []).slice();
      t.groups = Array.from(new Set([...(t.groups || []), ...groups]));
      const gained = t.groups.filter((g) => !before.includes(g));
      skipped.push(`${code}(${t.name})${gained.length ? ` — 그룹 추가: ${gained.join(',')}` : ' — 이미 등록됨'}`);
      continue;
    }

    let name = args.name || null;
    if (!name) {
      name = args.market === 'US' ? await resolveNameUS(code) : await resolveNameKR(code);
      if (!name) {
        console.warn(`  [경고] ${code} 종목명 조회 실패 — 코드를 이름으로 넣습니다(나중에 직접 수정 권장)`);
        name = code;
      }
    }

    if (args.verify) {
      try {
        const v = args.market === 'US' ? await verifyUS(code) : await verifyKR(code);
        console.log(`  ✓ ${code} ${name} — 최근 종가 ${v.close} (${v.lastDate})`);
      } catch (e) {
        console.error(`  ✗ ${code} ${name} — 시세 검증 실패: ${e.message} → 추가하지 않습니다`);
        failed.push(`${code}: ${e.message}`);
        continue;
      }
    } else {
      console.log(`  + ${code} ${name} (검증 생략)`);
    }

    const entry = { code, name, market: args.market, groups: groups.slice() };
    entry.addedAt = new Date().toISOString().slice(0, 10);
    wl.tickers.push(entry);
    existing.add(code.toUpperCase());
    added.push(`${code}(${name})`);
  }

  if (added.length > 0) {
    // groupLabels 보정 — 라벨이 없으면 대시보드 필터에 코드가 그대로 노출됩니다.
    wl.groupLabels = wl.groupLabels || {};
    const DEFAULT_LABELS = {
      'watch-manual': '수동 관심종목',
      'us-core': '지수 대표(US)',
      'index-core': '지수 대표(KR)',
    };
    for (const g of groups) {
      if (!wl.groupLabels[g]) wl.groupLabels[g] = DEFAULT_LABELS[g] || g;
    }

    // 유니버스 이력 — 백테스트 해석용. 기준 버전은 남기고 수동 추가분을 접미사로 붙입니다.
    const today = new Date().toISOString().slice(0, 10);
    const base = String(wl.universeVersion || 'unversioned').replace(/\+manual-\d{4}-\d{2}-\d{2}$/, '');
    wl.universeVersion = `${base}+manual-${today}`;
    wl.manualAdditions = wl.manualAdditions || [];
    wl.manualAdditions.push({ date: today, market: args.market, codes: added, groups });
    wl.manualAdditionsNote =
      '수동 추가 이력. 규칙 기반 유니버스(코스피100/S&P40)와 구분해 백테스트를 해석하기 위한 기록입니다. 추가 시점 이전 구간에는 이 종목의 history가 없습니다.';
  }

  console.log('');
  if (added.length) console.log(`추가 ${added.length}건: ${added.join(', ')}`);
  if (skipped.length) console.log(`건너뜀 ${skipped.length}건: ${skipped.join(' | ')}`);
  if (failed.length) console.log(`실패 ${failed.length}건: ${failed.join(' | ')}`);
  console.log(`총 종목 수: ${wl.tickers.length} (KR ${wl.tickers.filter((t) => (t.market || 'KR') === 'KR').length} / US ${wl.tickers.filter((t) => t.market === 'US').length})`);

  if (args.dryRun) {
    console.log('\n--dry-run: 저장하지 않았습니다.');
  } else if (added.length || skipped.length) {
    fs.writeFileSync(WATCHLIST_PATH, JSON.stringify(wl, null, 2) + '\n', 'utf-8');
    console.log('\nconfig/watchlist.json 저장 완료');
  } else {
    console.log('\n변경 없음 — 저장 생략');
  }

  // GitHub Actions 요약 패널 출력
  if (process.env.GITHUB_STEP_SUMMARY) {
    const lines = [
      `### 관심종목 추가 (${args.market})`,
      '',
      `- 추가: ${added.length ? added.join(', ') : '없음'}`,
      `- 건너뜀: ${skipped.length ? skipped.join(', ') : '없음'}`,
      `- 실패: ${failed.length ? failed.join(', ') : '없음'}`,
      `- 총 종목: ${wl.tickers.length}`,
      '',
      added.length
        ? `재무 수집(${args.market === 'US' ? 'fundamentals-us' : 'quarterly-fundamentals'})과 daily-analysis 를 실행하면 점수가 채워집니다.`
        : '',
    ];
    fs.appendFileSync(process.env.GITHUB_STEP_SUMMARY, lines.join('\n') + '\n');
  }

  // 검증 실패만 있고 추가가 하나도 없으면 실패로 끝냅니다(오타를 조용히 넘기지 않기 위함).
  if (added.length === 0 && failed.length > 0) process.exit(1);
}

main().catch((e) => {
  console.error('추가 실패:', e);
  process.exit(1);
});
