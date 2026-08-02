'use strict';
const CLASSIFIER_VERSION = 'DC-1.3';

const NEG     = /해제|해소|재개|취소|철회|기각|각하|제외|종료/;   // 상태 종료 방향
const PENDING = /예고|우려|사유발생|사유추가|이의신청|신청서/;     // 미확정

// 거래소 시장조치 공시명은 "조치명 (사유)" 구조다. 확정/해제 판정은 조치명(head)으로만 한다.
// 사유(괄호)까지 보면 실측에서 두 방향 모두로 뒤집힌다(골든셋 2024-08~2026-08, 292종목):
//   "주권매매거래정지 (관리종목지정사유발생)"          → 확정 정지가 PENDING으로 격하 (13건)
//   "주권매매거래정지해제 (상장폐지에 따른 정리매매 개시)" → 상폐 확정이 DELISTING_REVIEW_RELEASE로 반전 (26건)
const NON_ACTION = /^(기타시장안내|투자유의안내|조회공시요구|기타경영사항|기타안내사항)/;
// 병합·감자·무상증자 등에 따른 하루이틀짜리 기술적 정지. 위험 신호가 아니므로 별도 타입으로 격리한다.
const TECHNICAL = /병합|분할|전자등록|말소|자본감소|감자|무상증자|액면|변경상장|주식배당/;

// 회사공시 오귀속 차단 (DC-1.3). 골든셋 회사공시 2,713건 실측 기준.
// ① 자회사의 결정을 모회사 state로 반영하면 모회사에 없던 희석 감점이 붙는다. 188건.
//    예) "유상증자결정(종속회사의주요경영사항)" 154건, "…(자회사의주요경영사항)" 26건
const SUBSIDIARY = /종속회사|자회사|계열회사/;
// ② 사채가 사라지거나 애초에 나오지 않은 건은 희석의 반대 방향인데 MEZZANINE_ISSUED로 잡혔다. 278건.
//    예) "자기전환사채만기전취득결정" 84건, "…발행후만기전사채취득" 130여건,
//        "자기사채(…)소각결정의건", "…사모신주인수권부사채미발행처리결정", "전환사채매수선택권행사자지정",
//        "소송등의판결(전환사채반환)"
const NOT_ISSUED = /만기전.{0,4}취득|소각|미발행|매수선택권|^소송등의/;

function classify(reportNm) {
  const nm = String(reportNm || '').replace(/\s/g, '');
  const body = nm.replace(/^\[[^\]]*\]/, '');        // [기재정정] 등 접두 제거
  const head = body.split(/[(（]/)[0];               // 조치명
  const reason = body.slice(head.length);            // 사유 — 타입 판정에 쓰지 않는다(TECHNICAL 제외)
  const out = [];

  // ── ① 거래소 시장조치: head 기준. 안내성 공시는 조치가 아니므로 이벤트를 만들지 않는다.
  if (!NON_ACTION.test(head)) {
    if (/관리종목/.test(head)) {
      out.push(PENDING.test(head) ? 'MANAGEMENT_DESIGNATION_PENDING'
             : NEG.test(head)     ? 'MANAGEMENT_RELEASE'
             :                      'MANAGEMENT_DESIGNATION');
    }
    if (/거래정지/.test(head)) {
      out.push(NEG.test(head)          ? 'TRADING_RESUME'
             : TECHNICAL.test(reason)  ? 'TRADING_HALT_TECHNICAL'
             : PENDING.test(head)      ? 'TRADING_HALT_PENDING'
             :                           'TRADING_HALT');
    }
    if (/상장폐지/.test(head)) {
      out.push(PENDING.test(head) ? 'DELISTING_REVIEW_PENDING'
             : NEG.test(head)     ? 'DELISTING_REVIEW_RELEASE'
             :                      'DELISTING_REVIEW');   // DELISTED 자동 판정 안 함
    }
    if (/투자주의환기/.test(head)) {
      out.push(PENDING.test(head) ? 'INVESTMENT_WARNING_PENDING'
             : NEG.test(head)     ? 'INVESTMENT_WARNING_RELEASE'
             :                      'INVESTMENT_WARNING');
    }
  }

  // ── ② 회사 공시: "주요사항보고서(유상증자결정)" 구조라 조치명이 괄호 안에 있다. 전문으로 판정한다.
  //    단 아래 두 부류는 발행 주체·방향이 달라 그대로 두면 감점이 잘못 붙는다(골든셋 2,713건 중 466건).
  if (!SUBSIDIARY.test(body) && !NOT_ISSUED.test(body)) {
    if (/전환사채|신주인수권부사채|교환사채/.test(body) && !NEG.test(body)) out.push('MEZZANINE_ISSUED');
    if (/유상증자/.test(body) && !NEG.test(body)) out.push('RIGHTS_OFFERING');
  }

  return out;
}

module.exports = { classify, CLASSIFIER_VERSION };
