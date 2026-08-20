/**
 * A5-3 D4 — 공시로 검증된 기업행위로 A3c의 istcTotqy를 A2a 조정주가 기준에 맞춘다.
 *
 * 배경·결정 경위는 docs/A5-3-peg-조정기준-결정브리프.md §16~17이 정본이다.
 * 이 파일은 §17.1의 판정 순서와 §16.2의 cumulativeSplitFactor 공식만 구현한다 —
 * 공시 자체를 수집하지 않는다(그건 별도 백필 단계, 아직 미구축). 호출부가
 * corporateActions(그 corp의 이벤트 배열)를 이미 분류된 형태로 넘긴다고 가정한다.
 *
 * **정수배 사건과 실질 사건은 다르게 다룬다(브리프 §16.1)** — splitLike(분할·병합·
 * 무상증자·무상감자)은 주식수만 바뀌고 가치는 안 바뀌므로 A2a 가격처럼 소급
 * 보정한다. capitalReal(유상증자·유상감자·합병)은 A3c가 이미 PIT로 옳게 기록한
 * 값이라 보정이 아니라 확인이 필요하고, 대부분 유보로 간다.
 */
'use strict';

const pit = require('./pitSelector');

/** 이벤트 category → 처리 방식. 브리프 §16.1·§16.3의 표를 그대로 코드로 옮긴 것. */
const CATEGORY_CLASS = {
  split: 'splitLike',
  reverseOrConsolidation: 'splitLike',
  bonusIssue: 'splitLike',
  haltLiftSplit: 'splitLike',
  capitalReductionFree: 'splitLike',        // 무상감자 (cr_mth에 "무상")
  capitalReductionPaid: 'capitalReal',       // 유상감자 (cr_mth에 "유상")
  capitalReductionUnknown: 'capitalReal',    // cr_mth 키워드 매칭 실패
  rightsOfferingThirdParty: 'capitalReal',   // ic_mthn=제3자배정 — 권리락 없음
  rightsOfferingShareholders: 'capitalReal', // ic_mthn=주주배정류 — 권리락 정밀공식 미검증
  mergerSpinoff: 'capitalReal',
};

/** capitalReal 카테고리 중 유보가 필요한 것과 그 사유 코드(브리프 §16.4·§17.1 6번).
 *  여기 없는 capitalReal(rightsOfferingThirdParty·capitalReductionPaid)은 그대로
 *  통과한다 — 보정도 유보도 안 한다. */
const CAPITAL_REAL_WITHHOLD = {
  rightsOfferingShareholders: 'RIGHTS_FORMULA_UNVERIFIED',
  capitalReductionUnknown: 'CAPITAL_REDUCTION_TYPE_UNKNOWN',
  mergerSpinoff: 'MERGER_UNHANDLED',
};

/**
 * 같은 시기에 카테고리가 겹치면 개별 처리를 포기한다(065170류, 무상증자+감자
 * 합성 사례가 실측으로 나왔다 — 브리프 §3.6). 창 크기는 실측 근거가 65일(065170)
 * 뿐이라 임시로 넉넉히 잡는다 — 코드 구현 시점의 잠정값이며 §16.6이 이미
 * 미해결로 남겨둔 값이다.
 */
const COMPOUND_WINDOW_DAYS = 90;

function toEpochDays(d) {
  return Math.floor(Date.parse(pit.normDate(d)) / 86400000);
}

/**
 * ★ splitLike와 capitalReal-유보는 게이트 방향이 반대다(2026-08-20 후속 세션,
 * 회귀 작성 중 발견 — 처음엔 둘 다 "레코드 이후 사건"으로 짰다가 주주배정
 * 실사례로 회귀가 잡아냈다).
 *
 * splitLike: 레코드가 사건보다 **먼저** 접수됐으면(사건이 미래) 그 레코드의
 *   raw 값은 아직 사건을 모른다 — 배수를 곱해 미래 기준으로 소급 보정한다.
 *   (§16.2 "선택된 레코드의 availableFrom 이후 사건")
 *
 * capitalReal 유보: 레코드가 사건과 **같거나 이후에** 접수됐으면 그 레코드의
 *   raw 값(진짜 신주 발행 등 실질 변화)은 이미 사건을 반영한 정상 값이다 —
 *   문제는 그 값 자체가 아니라 **그 시점의 A2a 가격이 권리락을 올바르게
 *   반영했는지 검증이 안 됐다는 것**이다(브리프 §3.6 미해결 지점). 그래서
 *   "사건이 이 레코드 시점까지 이미 일어났는가"로 게이트가 반대로 걸린다 —
 *   사건이 아직 안 일어난(레코드가 사건보다 먼저인) 옛 레코드는 그 사건과
 *   무관하므로 유보 대상이 아니다.
 */
function eventsAfterRecord(events, recordAvailableFrom) {
  return (events || []).filter((e) => e && e.disclosureDate
    && !pit.lte(e.disclosureDate, recordAvailableFrom));
}
function eventsAtOrBeforeRecord(events, recordAvailableFrom) {
  return (events || []).filter((e) => e && e.disclosureDate
    && pit.lte(e.disclosureDate, recordAvailableFrom));
}

/** 전체 이벤트(선후 무관) 중 서로 다른 두 이벤트가 COMPOUND_WINDOW_DAYS 이내로
 *  겹치는가 — 겹침은 레코드 vintage와 무관하게 그 corp의 history 자체의 성질이다. */
function hasCompoundOverlap(events) {
  const days = events.map((e) => toEpochDays(e.disclosureDate)).sort((a, b) => a - b);
  for (let i = 1; i < days.length; i++) {
    if (days[i] - days[i - 1] <= COMPOUND_WINDOW_DAYS) return true;
  }
  return false;
}

/**
 * istcTotqy_raw를 공시로 검증된 배수로 보정한다.
 *
 * 반환값의 withheldBy가 null이 아니면 value는 null이다 — 유보 사유가 있으면
 * 보정후 값을 만들지 않는다("정직한 점수", 절대 규칙 1).
 */
function adjustSharesOutstanding(rawShares, corporateActions, recordAvailableFrom) {
  if (typeof rawShares !== 'number' || rawShares <= 0) {
    return { value: null, factor: null, withheldBy: 'SHARES_MISSING', appliedEvents: [] };
  }
  const events = (corporateActions || []).filter((e) => e && e.disclosureDate);
  if (events.length === 0) {
    return { value: rawShares, factor: 1, withheldBy: null, appliedEvents: [] };
  }
  if (hasCompoundOverlap(events)) {
    return { value: null, factor: null, withheldBy: 'COMPOUND_EVENT', appliedEvents: events };
  }

  // capitalReal 유보 — 이미 이 레코드 시점까지 일어난 사건만 본다(위 설명).
  const past = eventsAtOrBeforeRecord(events, recordAvailableFrom);
  for (const e of past) {
    const withhold = CAPITAL_REAL_WITHHOLD[e.category];
    if (withhold) {
      return { value: null, factor: null, withheldBy: withhold, appliedEvents: [e] };
    }
  }

  // splitLike 보정 — 아직 안 일어난(레코드보다 미래인) 사건만 배수를 곱한다.
  const forward = eventsAfterRecord(events, recordAvailableFrom);
  let factor = 1;
  const applied = [];
  for (const e of forward) {
    const cls = CATEGORY_CLASS[e.category];
    if (cls === 'splitLike') {
      if (typeof e.multiplier !== 'number' || e.multiplier <= 0) {
        // 분류는 splitLike인데 배수가 없다 — 데이터 준비 단계의 결함이다.
        // 임의로 1을 가정하지 않고 유보한다(교훈57, 모르는 것은 0이 아니다).
        return { value: null, factor: null, withheldBy: 'DART_MATCH_FAIL', appliedEvents: forward };
      }
      factor *= e.multiplier;
      applied.push({ rceptNo: e.rceptNo, disclosureDate: e.disclosureDate,
                     category: e.category, multiplier: e.multiplier });
      continue;
    }
    if (cls === 'capitalReal') {
      // 아직 안 일어난 capitalReal 사건은 이 레코드와 무관하다(위 설명) — 통과.
      continue;
    }
    // 알 수 없는 category — 분류표에 없는 값이 들어왔다. 조용히 통과시키지 않는다.
    return { value: null, factor: null, withheldBy: 'DART_MATCH_FAIL', appliedEvents: forward };
  }

  return { value: rawShares * factor, factor, withheldBy: null, appliedEvents: applied };
}

module.exports = {
  CATEGORY_CLASS, CAPITAL_REAL_WITHHOLD, COMPOUND_WINDOW_DAYS,
  adjustSharesOutstanding,
};
