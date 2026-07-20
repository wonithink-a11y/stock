#!/usr/bin/env node
/**
 * KRX 투자자별 거래실적(시장 전체) → docs/data/market_flows.json
 *   코스피/코스닥의 일별 투자자별 순매수(개인·외국인·금융투자·투신·연기금·보험·기타법인 등)
 *
 * 데이터: data.krx.co.kr getJsonData, bld=dbms/MDC/STAT/standard/MDCSTAT02201 (투자자별 거래실적)
 *   GitHub Actions에서 실행(서버는 KRX 미접속). 외부 의존성 없음(Node 18+ fetch).
 *
 * ⚠ 첫 실행 단계: KRX 응답 컬럼명을 로그로 출력합니다. 그 로그를 보고
 *   카테고리 매핑과 대시보드 그래프를 확정합니다(파라미터가 빗나가면 rows 0으로 나옴).
 */
'use strict';

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, 'docs', 'data', 'market_flows.json');
const ENDPOINT = 'http://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd';
const BLD = 'dbms/MDC/STAT/standard/MDCSTAT02201'; // 투자자별 거래실적(MDCSTAT022)
const LOOKBACK = Number(process.env.FLOW_LOOKBACK_DAYS || 25);

function kstYmd(off = 0) {
  const d = new Date(Date.now() + 9 * 3600 * 1000 - off * 86400 * 1000);
  return d.toISOString().slice(0, 10).replace(/-/g, '');
}

async function fetchMarket(mktId) {
  const body = new URLSearchParams({
    bld: BLD, locale: 'ko_KR',
    inqTpCd: '2',      // 2 = 일별추이
    trdVolVal: '2',    // 1 = 거래량, 2 = 거래대금
    askBid: '3',       // 1 = 매도, 2 = 매수, 3 = 순매수
    mktId,             // STK = 코스피, KSQ = 코스닥
    strtDd: kstYmd(LOOKBACK), endDd: kstYmd(0),
    detailView: '1',   // 기관 세부(연기금 등) 표시
    money: '1', csvxls_isNo: 'false',
  });
  const res = await fetch(ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
      'Referer': 'http://data.krx.co.kr/contents/MDC/MDI/mdiLoader/index.cmd?menuId=MDC0201020301',
      'User-Agent': 'Mozilla/5.0',
    },
    body: body.toString(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const j = await res.json();
  const rows = j.output || j.OutBlock_1 || j.block1 || [];
  return { rows, keys: rows[0] ? Object.keys(rows[0]) : [] };
}

async function main() {
  const out = { updatedAt: new Date().toISOString(), source: 'KRX MDCSTAT02201', markets: {} };
  for (const [name, mktId] of [['KOSPI', 'STK'], ['KOSDAQ', 'KSQ']]) {
    try {
      const { rows, keys } = await fetchMarket(mktId);
      console.log(`\n[${name}] ${rows.length}행`);
      console.log(`  컬럼(${keys.length}): ${keys.join(', ')}`);
      if (rows[0]) console.log(`  첫 행: ${JSON.stringify(rows[0])}`);
      out.markets[name] = { rows };
    } catch (e) {
      console.warn(`[${name}] 실패: ${e.message}`);
      out.markets[name] = { rows: [], error: e.message };
    }
  }
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  fs.writeFileSync(OUT, JSON.stringify(out, null, 2) + '\n', 'utf8');
  const n = Object.values(out.markets).reduce((a, m) => a + (m.rows ? m.rows.length : 0), 0);
  console.log(`\n✅ 총 ${n}행 → ${OUT}`);
  if (!n) console.log('⚠ 0행입니다 — KRX 파라미터(mktId/inqTpCd 등) 조정 필요. 위 로그의 컬럼/에러를 공유해 주세요.');
}

main().catch((e) => { console.error('❌', e); process.exit(1); });
