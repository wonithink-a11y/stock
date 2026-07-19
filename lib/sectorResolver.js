/**
 * sectorResolver.js (v1.0)
 *
 * DART 기업개황 API의 induty_code(한국표준산업분류 KSIC)를 criteria.json의
 * sectorType으로 변환합니다. config/sector-map.json 을 규칙 테이블로 사용.
 *
 * 해결 순서: byTicker → bySicPrefix(최장 일치) → byNamePattern → 'general'
 *
 * 설계 원칙 — "조용한 오분류보다 시끄러운 미분류":
 *  - SIC 코드를 못 받았으면 general로 채점하되 resolved:false 를 남겨
 *    엔진이 unmappedSector 경고를 띄우게 한다.
 *  - byTicker의 name과 실제 종목명이 다르면 종목코드 오기입이므로 경고한다.
 *    (틀린 코드가 조용히 엉뚱한 업종 기준을 적용하는 사고를 막는 장치)
 */

const fs = require('fs');
const path = require('path');

let cachedMap = null;

function loadMap(mapPath) {
  if (cachedMap && !mapPath) return cachedMap;
  const p = mapPath || path.join(__dirname, '..', 'config', 'sector-map.json');
  const m = JSON.parse(fs.readFileSync(p, 'utf-8'));
  if (!mapPath) cachedMap = m;
  return m;
}

/** 이름 정규화: 공백·(주)·우선주 접미사 제거 후 비교 */
function normalizeName(name) {
  return String(name || '')
    .replace(/\(주\)|주식회사/g, '')
    .replace(/\s+/g, '')
    .trim();
}

/** bySicPrefix 최장 일치 */
function matchSicPrefix(sicCode, table) {
  if (!sicCode) return null;
  const code = String(sicCode).trim();
  if (!code) return null;
  const keys = Object.keys(table).sort((a, b) => b.length - a.length);
  for (const k of keys) {
    if (code.startsWith(k)) return { sectorType: table[k], matchedPrefix: k };
  }
  return null;
}

function matchNamePattern(name, patterns) {
  const n = normalizeName(name);
  if (!n) return null;
  for (const rule of patterns || []) {
    let re;
    try {
      re = new RegExp(rule.pattern);
    } catch (e) {
      continue; // 잘못된 정규식은 무시 (테이블 오타가 파이프라인을 죽이지 않도록)
    }
    if (re.test(n)) return { sectorType: rule.sectorType, matchedPattern: rule.pattern };
  }
  return null;
}

/**
 * @param {object} input
 * @param {string} input.ticker   종목코드 (예: '005930')
 * @param {string} input.name     종목명 (watchlist 기준)
 * @param {string} [input.sicCode] DART induty_code
 * @param {object} [map]          sector-map.json 파싱 객체 (미제공 시 파일 로드)
 * @returns {{sectorType, resolved, resolvedBy, detail, warnings}}
 */
function resolveSector(input, map) {
  const m = map || loadMap();
  const warnings = [];
  const ticker = String(input.ticker || '').trim();
  const name = input.name || '';
  const sicCode = input.sicCode || input.indutyCode || null;

  // 1) byTicker — 수동 고정이 항상 이깁니다
  const manual = m.byTicker && m.byTicker[ticker];
  if (manual) {
    const expected = normalizeName(manual.name);
    const actual = normalizeName(name);
    // 이름 대조: 한쪽이 비어 있으면 검증 생략
    if (expected && actual && expected !== actual) {
      warnings.push({
        code: 'tickerNameMismatch',
        message: `sector-map.byTicker['${ticker}']의 종목명이 '${manual.name}'인데 watchlist에는 '${name}'입니다. 종목코드 오기입 가능성 — 업종 기준이 잘못 적용될 수 있습니다.`,
      });
    }
    return {
      sectorType: manual.sectorType,
      resolved: true,
      resolvedBy: 'byTicker',
      detail: { ticker, mappedName: manual.name, sicCode },
      warnings,
    };
  }

  // 2) bySicPrefix — DART 표준산업분류
  const bySic = matchSicPrefix(sicCode, m.bySicPrefix || {});
  if (bySic) {
    return {
      sectorType: bySic.sectorType,
      resolved: true,
      resolvedBy: 'bySicPrefix',
      detail: { sicCode, matchedPrefix: bySic.matchedPrefix },
      warnings,
    };
  }

  // 3) byNamePattern — 최후 수단
  const byName = matchNamePattern(name, m.byNamePattern);
  if (byName) {
    warnings.push({
      code: 'sectorGuessedByName',
      message: `'${name}'의 업종을 사명 패턴(${byName.matchedPattern})으로 추정했습니다. sector-map.byTicker에 고정하는 것을 권장합니다.`,
    });
    return {
      sectorType: byName.sectorType,
      resolved: true,
      resolvedBy: 'byNamePattern',
      detail: { sicCode, matchedPattern: byName.matchedPattern },
      warnings,
    };
  }

  // 4) 기본값
  // SIC 코드가 있는데 테이블에 없다 = 기본 기준이 맞는 업종(제조업 등). 정상.
  // SIC 코드 자체가 없다 = 진짜 미분류. 경고.
  const hasSic = Boolean(sicCode);
  return {
    sectorType: (m.default || 'general'),
    resolved: hasSic,
    resolvedBy: hasSic ? 'default(sicKnown)' : 'default(sicMissing)',
    detail: { sicCode },
    warnings,
  };
}

/**
 * watchlist 전체를 한 번에 해석해 검수용 표를 만듭니다.
 * 확대 직후 `node -e "require('./lib/sectorResolver').report(...)"` 로 눈 검수하세요.
 */
function resolveAll(items, map) {
  const m = map || loadMap();
  return items.map((it) => {
    const r = resolveSector(it, m);
    return {
      ticker: it.ticker || it.code,
      name: it.name,
      sicCode: it.sicCode || it.indutyCode || null,
      sectorType: r.sectorType,
      resolvedBy: r.resolvedBy,
      resolved: r.resolved,
      warnings: r.warnings.map((w) => w.code),
    };
  });
}

function report(items, map) {
  const rows = resolveAll(items, map);
  const counts = {};
  for (const r of rows) counts[r.sectorType] = (counts[r.sectorType] || 0) + 1;

  const lines = [];
  lines.push('업종 분류 결과');
  lines.push('='.repeat(72));
  for (const r of rows) {
    const flag = r.warnings.length ? `  ⚠ ${r.warnings.join(',')}` : '';
    const risky = r.resolvedBy === 'byNamePattern' || r.resolvedBy === 'default(sicMissing)' ? ' ←검수' : '';
    lines.push(
      `${String(r.ticker).padEnd(8)} ${String(r.name).padEnd(18)} ${String(r.sicCode || '-').padEnd(8)} ` +
        `${r.sectorType.padEnd(13)} ${r.resolvedBy}${risky}${flag}`
    );
  }
  lines.push('='.repeat(72));
  lines.push('업종별 종목 수: ' + JSON.stringify(counts));
  const needReview = rows.filter((r) => r.resolvedBy === 'byNamePattern' || !r.resolved);
  lines.push(`검수 필요: ${needReview.length}건`);
  return lines.join('\n');
}

module.exports = { resolveSector, resolveAll, report, loadMap };
