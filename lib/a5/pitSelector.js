/**
 * A5 PIT 선택기 — asOf 시점에 알 수 있었던 재무 레코드를 고른다.
 *
 * **A5에서 가장 조용하게 무너지는 자리다.** 여기가 틀려도 점수·등급은 정상으로
 * 보이고 백테스트만 좋아진다. 그래서 규칙을 한 곳에 두고 회귀로 못 박는다.
 *
 *   1  availableFrom <= asOf 인 레코드만 후보다      (미래를 보지 않는다)
 *   2  그중 fiscalYear가 최대인 것                    (가장 최근 사업연도)
 *   3  동률이면 availableFrom이 최대인 것             (그 시점까지의 마지막 정정본)
 *
 * 3번이 정정공시를 다룬다. 같은 (corp, fiscalYear)에 서로 다른 availableFrom이
 * 여럿인 것은 중복이 아니라 사실이고(A3가 병합하지 않는 이유), asOf 시점에 알 수
 * 있던 것은 **그 시점 이전의 마지막 정정본**이다. 최신 정정본을 쓰면 미래를 본다.
 *
 * 이력(roeHistory5y 등)은 **연도마다 1~3을 따로 적용한다.** 한 번 고른 레코드의
 * 전기·전전기 열을 쓰면 그 값들의 availableFrom이 '그 보고서의 접수일'이 되어
 * 과거를 실제보다 늦게 안 것으로 기록한다(교훈47).
 */
'use strict';

/**
 * availableFrom을 비교용 'YYYY-MM-DD'로 정규화한다.
 *
 * A3는 'YYYY-MM-DD', A3b는 'YYYYMMDD'를 쓴다 — A3b 계약(FN-1.5)이 선언한 원본
 * 포맷이므로 그건 바꾸지 않는다. 여기는 비교 직전의 방어일 뿐이다.
 *
 * 정규화 없이 문자열째 비교하면 '-'(0x2D)가 숫자(0x30~)보다 작아, 두 값의 연도가
 * 같을 때만 다섯 번째 글자에서 압축형이 항상 "더 크다(미래)"로 읽힌다. 그 결과가
 * asOf와 같은 해의 레코드 전부가 조용히 탈락하는 것이었다(실측 2,752/25,531,
 * 2026-08-12) — 값이 아니라 포맷이 갈랐는데 조회 결과는 '데이터가 없다'로 보인다.
 *
 * 모르는 형식은 조용히 잘못 비교하지 않고 즉시 던진다(교훈57 — 모르는 것은 0이
 * 아니다). 두 형식만 허용해야 이 함수가 "아무 문자열이나 받아준다"로 느슨해지지
 * 않는다.
 */
function normDate(d) {
  const s = String(d);
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  if (/^\d{8}$/.test(s)) return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
  throw new Error(`pitSelector: 알 수 없는 날짜 형식 '${s}' — 'YYYY-MM-DD' 또는 'YYYYMMDD'만 받는다`);
}

/** 정규화 후 문자열 비교. 고정 폭이라 정규화되면 사전순이 시간순이다. */
function lte(a, b) {
  return normDate(a) <= normDate(b);
}

/**
 * asOf 시점의 레코드 하나. 후보가 없으면 null (그 시점에 아무것도 몰랐다는 뜻).
 *
 * records는 한 corp의 것이어야 한다. 여러 corp를 섞어 넘기면 남의 재무를 고른다 —
 * 호출부가 corp로 먼저 거른다.
 */
function selectAsOf(records, asOf) {
  let best = null;
  for (const r of records) {
    if (!r || !r.availableFrom) continue;
    if (!lte(r.availableFrom, asOf)) continue;          // 규칙 1 — 미래를 보지 않는다
    if (best === null) { best = r; continue; }
    if (r.fiscalYear > best.fiscalYear) { best = r; continue; }   // 규칙 2
    if (r.fiscalYear === best.fiscalYear                          // 규칙 3
        && normDate(r.availableFrom) > normDate(best.availableFrom)) best = r;
  }
  return best;
}

/**
 * 특정 사업연도의 레코드. 그 연도 안에서 asOf 이전의 마지막 정정본을 고른다.
 * 이력 조회의 단위이며, 여기서도 규칙 1과 3이 그대로 적용된다.
 */
function selectFiscalYear(records, fiscalYear, asOf) {
  let best = null;
  for (const r of records) {
    if (!r || r.fiscalYear !== fiscalYear || !r.availableFrom) continue;
    if (!lte(r.availableFrom, asOf)) continue;
    if (best === null || normDate(r.availableFrom) > normDate(best.availableFrom)) best = r;
  }
  return best;
}

/**
 * 최신 사업연도부터 n개. **연도마다 따로 고른다.**
 *
 * 빈 해는 null로 남긴다 — 앞으로 당겨 채우면 5년 이력이 실제보다 촘촘해 보이고,
 * roeConsistency(최솟값)가 없는 해를 건너뛴 낙관적인 값이 된다. 결측은 결측이다.
 */
function selectHistory(records, asOf, n) {
  const latest = selectAsOf(records, asOf);
  if (!latest) return [];
  const out = [];
  for (let i = 0; i < n; i++) {
    out.push(selectFiscalYear(records, latest.fiscalYear - i, asOf));
  }
  return out;
}

/**
 * 그 레코드가 asOf 기준 얼마나 묵었는가. confidence.freshness의 재료다.
 *
 * 정책이 freshness를 선언해두고 "파이프라인 미구축이라 항상 null"이라 적어둔 자리를
 * 채운다. 연간 재무는 본질적으로 최대 1년 이상 묵으므로, 이 값을 '나쁨'으로 읽는
 * 척도가 아니라 **얼마나 묵었는지의 사실**로 둔다. 점수화는 정책의 몫이다.
 */
function freshnessDays(record, asOf) {
  if (!record || !record.availableFrom) return null;
  const ms = Date.parse(normDate(asOf)) - Date.parse(normDate(record.availableFrom));
  if (Number.isNaN(ms)) return null;
  return Math.floor(ms / 86400000);
}

/**
 * 미래 참조 검사. 고른 레코드가 규칙 1을 어겼는지 사후에 다시 본다.
 *
 * 선택기가 규칙 1을 이미 지키므로 구성상 항상 통과할 것 같지만, 그렇지 않다 —
 * 호출부가 선택기를 거치지 않고 레코드를 직접 넣을 수 있고 그것이 실제 위험이다.
 * 여기는 '선택이 옳았는가'가 아니라 '무엇을 쓰든 미래가 아닌가'를 본다.
 */
function violatesPit(record, asOf) {
  if (!record || !record.availableFrom) return false;
  return !lte(record.availableFrom, asOf);
}

module.exports = {
  normDate, lte, selectAsOf, selectFiscalYear, selectHistory, freshnessDays, violatesPit,
};
