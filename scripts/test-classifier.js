#!/usr/bin/env node
/**
 * DC-1.3 Classifier 회귀 테스트
 *
 * 케이스는 전부 TASK-2A 골든셋(2024-08~2026-08, 292종목, 공시 55,539건)에서
 * 실제로 관측된 report_nm이다. 지어낸 문자열은 넣지 않는다.
 *   node scripts/test-classifier.js
 */
'use strict';
const assert = require('assert');
const { classify, CLASSIFIER_VERSION } = require('../lib/eventClassifiers/dart');

let pass = 0, fail = 0;
function eq(reportNm, expected, note) {
  const got = classify(reportNm);
  try {
    assert.deepStrictEqual(got, expected);
    pass++;
  } catch {
    fail++;
    console.log(`[FAIL] ${reportNm}\n       기대 ${JSON.stringify(expected)}\n       실제 ${JSON.stringify(got)}${note ? '\n       ' + note : ''}`);
  }
}

assert.strictEqual(CLASSIFIER_VERSION, 'DC-1.3');

/* ── 기본 형태 (DC-1.1에서 이어짐) ───────────────────────────── */
eq('관리종목지정', ['MANAGEMENT_DESIGNATION']);
eq('관리종목지정해제', ['MANAGEMENT_RELEASE']);
eq('상장폐지이의신청', ['DELISTING_REVIEW_PENDING']);
eq('관리종목지정및매매거래정지', ['MANAGEMENT_DESIGNATION', 'TRADING_HALT']);
eq('현금ㆍ현물배당결정', []);

/* ── ① 사유(괄호)가 조치를 뒤집던 버그 — 실측 269건 ─────────── */
// 확정 정지가 PENDING으로 격하되던 건 (13건)
eq('주권매매거래정지 (관리종목지정사유발생)', ['TRADING_HALT']);
eq('주권매매거래정지 (상장적격성 실질심사 대상 (사유발생))', ['TRADING_HALT']);
eq('주권매매거래정지기간변경 (상장폐지 사유 발생)', ['TRADING_HALT']);
// 상폐 확정을 "해제"로 읽던 건 (26건) — DELISTING_REVIEW_RELEASE가 나오면 안 된다
eq('주권매매거래정지해제 (상장폐지에 따른 정리매매 개시)', ['TRADING_RESUME']);
// 정지가 지속되는데 RESUME으로 뒤집히던 건 (10건)
eq('주권매매거래정지기간변경 (상장폐지 사유 해소)', ['TRADING_HALT']);
eq('주권매매거래정지기간변경 (개선기간 부여)', ['TRADING_HALT']);

/* ── ② 안내성 공시는 조치가 아니다 — 실측 371건 ─────────────── */
eq('기타시장안내 (상장폐지 관련)', []);
eq('기타시장안내 (코스닥시장위원회 개최 결과 및 상장폐지 결정 안내)', []);
eq('기타시장안내 (관리종목지정우려종목)', []);
eq('기타시장안내 (형식적 상장폐지 사유 해소 및 매매거래정지 지속 안내)', [],
   '"해소"만 보고 TRADING_RESUME을 내던 건 — 본문은 정지 지속이다');
eq('투자유의안내 (상장폐지 기준 해당)', []);
eq('기타경영사항(자율공시) (상장폐지결정 효력정지 가처분 신청)', []);
eq('조회공시요구(풍문또는보도) (감사의견 비적정설)', []);

/* ── ③ 기술적 정지 격리 — 실측 118건 ───────────────────────── */
eq('주권매매거래정지 (주식의 병합, 분할 등 전자등록 변경, 말소)', ['TRADING_HALT_TECHNICAL']);
eq('주권매매거래정지 (자본감소)', ['TRADING_HALT_TECHNICAL']);
eq('주권매매거래정지 (무상증자)', ['TRADING_HALT_TECHNICAL']);
eq('주권매매거래정지기간변경 (감자 주권 변경상장)', ['TRADING_HALT_TECHNICAL']);
// 위험 사유의 정지는 격리 대상이 아니다
eq('주권매매거래정지 (투자자 보호)', ['TRADING_HALT']);
eq('주권매매거래정지 (불성실공시법인 지정)', ['TRADING_HALT']);

/* ── ④ 복합·정정·회사공시 ───────────────────────────────────── */
eq('내부결산시점관리종목지정ㆍ형식적상장폐지ㆍ상장적격성실질심사사유발생',
   ['MANAGEMENT_DESIGNATION_PENDING', 'DELISTING_REVIEW_PENDING']);
eq('[기재정정]내부결산시점관리종목지정ㆍ형식적상장폐지ㆍ상장적격성실질심사사유발생',
   ['MANAGEMENT_DESIGNATION_PENDING', 'DELISTING_REVIEW_PENDING']);
eq('주요사항보고서(유상증자결정)', ['RIGHTS_OFFERING']);
eq('[기재정정]주요사항보고서(전환사채권발행결정)', ['MEZZANINE_ISSUED']);
eq('매매거래정지및정지해제(중요내용공시)', ['TRADING_RESUME']);
eq('주권매매거래정지해제 (감자 주권 변경상장)', ['TRADING_RESUME'],
   '기술적 정지의 해제도 RESUME이다 — 상태를 NORMAL로 되돌릴 뿐이라 무해하다');

/* ── ⑤ 자회사 결정은 모회사 이벤트가 아니다 (DC-1.3) — 실측 188건 ── */
eq('유상증자결정(종속회사의주요경영사항)', [], '모회사에 -10이 잘못 붙던 건 154건');
eq('[기재정정]유상증자결정(종속회사의주요경영사항)', []);
eq('유상증자결정(자회사의주요경영사항)', []);
eq('주요사항보고서(유상증자결정)(자회사의주요경영사항)', []);
eq('주요사항보고서(교환사채권발행결정)(자회사의주요경영사항)', []);
eq('유상증자결정(자회사의주요경영사항)(주주배정-현물출자)', []);

/* ── ⑥ 사채 소멸·미발행은 희석이 아니다 (DC-1.3) — 실측 278건 ──── */
eq('주요사항보고서(자기전환사채만기전취득결정)', [], '자기사채 취득 = 희석 축소인데 -8이 붙던 건 84건');
eq('전환사채(해외전환사채포함)발행후만기전사채취득', []);
eq('신주인수권부사채(해외신주인수권부사채포함)발행후만기전사채취득(제22회차)', []);
eq('기타경영사항(자율공시)(자기사채(제13회전환사채)소각결정의건)', []);
eq('기타주요경영사항(제23회차무기명식이권부무보증비분리형사모신주인수권부사채미발행처리결정)', []);
eq('주요사항보고서(전환사채매수선택권행사자지정)', []);
eq('소송등의판결ㆍ결정(일정금액이상의청구)(전환사채반환)', []);
// 반대로 자기사채를 다시 시장에 파는 건 희석 재개다 — 유지
eq('주요사항보고서(자기전환사채매도결정)', ['MEZZANINE_ISSUED'], '자기사채 매도 = 전환권 재유통, 213건');
// 모회사 자신의 결정은 그대로 남아야 한다(과잉 필터 방어)
eq('주요사항보고서(유상증자결정)', ['RIGHTS_OFFERING']);
eq('주요사항보고서(전환사채권발행결정)', ['MEZZANINE_ISSUED']);
eq('주요사항보고서(신주인수권부사채권발행결정)', ['MEZZANINE_ISSUED']);

/* ── ⑦ 구조 불변식 ─────────────────────────────────────────── */
const MARKET_ACTION = /^(MANAGEMENT|TRADING|DELISTING|INVESTMENT)_/;
for (const head of ['기타시장안내', '투자유의안내', '조회공시요구', '기타경영사항', '기타안내사항']) {
  const got = classify(`${head} (관리종목지정 및 상장폐지 및 매매거래정지 및 투자주의환기)`);
  if (got.some((t) => MARKET_ACTION.test(t))) {
    fail++; console.log(`[FAIL] 안내성 공시가 시장조치 이벤트를 생성: ${head} → ${JSON.stringify(got)}`);
  } else pass++;
}
// 사유부만 바꿔서는 조치 타입이 달라지면 안 된다(TECHNICAL 격리 제외)
{
  const base = classify('주권매매거래정지 (투자자 보호)');
  const alt = classify('주권매매거래정지 (풍문 또는 보도 관련)');
  if (JSON.stringify(base) === JSON.stringify(alt)) pass++;
  else { fail++; console.log(`[FAIL] 사유 변화로 조치 타입이 흔들림: ${JSON.stringify(base)} vs ${JSON.stringify(alt)}`); }
}
// 빈 입력 방어
for (const v of [null, undefined, '', '   ']) {
  if (Array.isArray(classify(v)) && classify(v).length === 0) pass++;
  else { fail++; console.log(`[FAIL] 빈 입력 방어: ${JSON.stringify(v)}`); }
}

console.log(`\n${CLASSIFIER_VERSION}: ${pass} passed, ${fail} failed`);
process.exit(fail === 0 ? 0 : 1);
