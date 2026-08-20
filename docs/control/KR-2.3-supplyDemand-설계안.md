# KR-2.3 설계안 — supplyDemand 축 재정의 (외국인·기관 20일 순매수)

```
발행   2026-08-19 · Claude
상태   설계안 — 아직 아무 파일도 안 만들었다. 사용자 GO 이후 실제 구현 착수
근거   docs/control/handoff/DEEPSEEK-2-A4-marginal-IC-검증.md
       docs/verification/DEEPSEEK-2-A4-marginal-IC-결과.md
       research/strategy-lab/data/a4/a4-analysis-results.json ·
       a4-marginal-analysis.json
```

## 이 문서의 성격

Q1~Q5(창 길이·개인축·대형주 한정·2슬롯 제거·weight)가 전부 결론에 도달한 뒤
작성하는 **구현 스펙**이다. 여기 있는 JSON·코드는 전부 **제안**이고, 실제로
`config/criteria/`에 파일을 만들거나 `lib/scoringEngine.js`·`lib/a5/resolver.js`를
고치는 건 이 설계안 승인 이후 별도 작업이다(규칙 5·6 — 동결 스냅샷·정책 버전 승격).

## 구현 범위가 예상보다 넓다 — 중요한 재확인

당초 "criteria 새 버전 + resolver.js에 빌더 함수 추가"로만 생각했는데,
`lib/scoringEngine.js`의 `scoreSupplyDemand()`를 다시 읽어보니 fundamental
축과 달리 **criteria를 순회하지 않고 필드명이 함수 안에 하드코딩**돼 있다:

```js
// 현재 코드 (lib/scoringEngine.js) — s.foreignTrend5d 같은 필드명이 리터럴이다
const foreignScore = trendToScore(s.foreignTrend5d);
detail.foreignNetBuy5d = { label: cfg.foreignNetBuy5d.label, ... };
const institutionScore = trendToScore(s.institutionTrend5d);
detail.institutionNetBuy5d = { label: cfg.institutionNetBuy5d.label, ... };
// + largeShareholderChange, buybackOrRetirement 블록
```

**즉 criteria.json만 새로 만들면 안 된다.** `scoreSupplyDemand()` 함수 자체를
고쳐야 새 필드명(`foreignTrend20d` 등)을 읽고, 제거하기로 한 2개 블록
(largeShareholderChange·buybackOrRetirement)을 뺄 수 있다. 이건 BF-1.1 §7
A5 인수 조건 4("운영과 다른 계산식을 쓰지 않는다")에 따라 연구용으로 따로
만들면 안 되고 **production 함수 자체**를 고쳐야 한다 — 지금까지 이 세션에서
한 작업(resolver.js에 새 함수만 추가) 보다 변경 범위가 크다.

## 변경 파일 목록 (제안)

| 파일 | 종류 | 내용 |
|---|---|---|
| `config/criteria/KR-2.3.json` | 신규(동결 스냅샷) | KR-2.2를 복사 후 `supplyDemand.metrics`만 교체 |
| `config/policies/registry.json` | 수정 | `criteria.KR.version`: `"2.2"` → `"2.3"` |
| `lib/scoringEngine.js` | **수정** | `scoreSupplyDemand()` 필드명 교체 + 2개 블록 제거 |
| `lib/a5/supplyDemandFrom.js` | 신규 | A4 원자료 → `{foreignTrend20d, institutionTrend20d}` (technicalFrom.js와 같은 패턴) |
| `lib/a5/resolver.js` | 수정 | `resolve()`에 supplyDemand 옵션 인자 추가(candles/dividendEps와 같은 패턴) |

## 1. criteria.json — supplyDemand.metrics (제안)

```json
"supplyDemand": {
  "description": "한국 시장 특화 - 수급 주체별 매매 동향 (KRX 데이터 기준, 20일 창)",
  "metrics": {
    "foreignNetBuy20d": { "label": "외국인 20일 순매수 추세", "weight": 0.50 },
    "institutionNetBuy20d": { "label": "기관 20일 순매수 추세", "weight": 0.50 }
  }
}
```

**weight 50:50인 이유**: marginal IC(d120)는 외국인이 더 강하고(t=15.6 vs
10.1), 단변량 IC는 기관이 더 강하다(t=25.1 vs 14.5) — 두 방법론이 순위를
뒤집는다. 이 프로젝트가 반복적으로 경계해온 과최적화(정찰 스크립트들의
"threshold·가중치 조합은 확정하지 않는다" 원칙)를 그대로 적용해, 노이즈가
낀 점추정치로 정밀한 비율(예: 55:45)을 정하지 않고 동률로 둔다.

**largeShareholderChange·buybackOrRetirement 제거**: 원자료 자체가 없다
(2턴 전 확인). 분모(19칸)에서 2칸이 빠진다.

## 2. `lib/a5/supplyDemandFrom.js` (신규 — technicalFrom.js 패턴)

```js
/**
 * A5 supplyDemand 축 — A4(수급) 원자료에서 20일 창 순매수 추세를 유도한다.
 *
 * scripts/probe-a4-supplydemand-vertical-slice.js:trendFromWindow()과 같은
 * 분류 규칙을 그대로 쓴다(정찰에서 이미 검증된 로직 — 새로 안 만든다).
 */
'use strict';

const FOREIGN_CATEGORIES = ['외국인', '기타외국인'];
const INSTITUTION_CATEGORIES = ['금융투자', '보험', '투신', '사모', '은행', '기타금융', '연기금', '기타법인'];
const WINDOW = 20;

function netOf(rec, categories) {
  let net = 0;
  for (const c of categories) net += (rec.buyAmount[c] || 0) - (rec.sellAmount[c] || 0);
  return net;
}

function trendFromWindow(window, categories) {
  if (window.length === 0) return null;
  let daysBuy = 0;
  for (const r of window) if (netOf(r, categories) > 0) daysBuy++;
  const total = window.length;
  if (daysBuy === total) return 'consistentBuy';
  if (daysBuy === 0) return 'consistentSell';
  if (daysBuy > total / 2) return 'netBuy';
  if (daysBuy < total / 2) return 'netSell';
  return 'neutral';
}

/**
 * records: 그 ticker의 A4 레코드(날짜 오름차순 아니어도 됨, 여기서 정렬).
 * asOf 이후 레코드가 섞이면 조용히 넘기지 않고 던진다(technicalFrom.js와 같은 PIT 가드).
 */
function supplyDemandFrom(records, asOf) {
  const future = records.filter((r) => r.date > asOf);
  if (future.length > 0) {
    throw new Error(`supplyDemandFrom: asOf(${asOf}) 이후 레코드 ${future.length}건이 섞였다`);
  }
  const sorted = [...records].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const window = sorted.filter((r) => r.date <= asOf).slice(-WINDOW);

  return {
    values: {
      foreignTrend20d: trendFromWindow(window, FOREIGN_CATEGORIES),
      institutionTrend20d: trendFromWindow(window, INSTITUTION_CATEGORIES),
    },
    windowSize: window.length,
    lastDate: window.length ? window[window.length - 1].date : null,
  };
}

module.exports = { supplyDemandFrom, trendFromWindow, netOf, FOREIGN_CATEGORIES, INSTITUTION_CATEGORIES };
```

## 3. `lib/scoringEngine.js` — `scoreSupplyDemand()` 변경 (제안 diff)

```diff
 function scoreSupplyDemand(data, criteria) {
   const cfg = criteria.supplyDemand.metrics;
   const s = data.supplyDemand || {};
   const items = [];
   const detail = {};
   const trendToScore = (trend) => { ... };  // 변경 없음

-  const foreignScore = trendToScore(s.foreignTrend5d);
-  detail.foreignNetBuy5d = { label: cfg.foreignNetBuy5d.label, trend: s.foreignTrend5d, score: foreignScore };
-  items.push({ score: foreignScore, weight: cfg.foreignNetBuy5d.weight });
+  const foreignScore = trendToScore(s.foreignTrend20d);
+  detail.foreignNetBuy20d = { label: cfg.foreignNetBuy20d.label, trend: s.foreignTrend20d, score: foreignScore };
+  items.push({ score: foreignScore, weight: cfg.foreignNetBuy20d.weight });

-  const institutionScore = trendToScore(s.institutionTrend5d);
-  detail.institutionNetBuy5d = { ... };
-  items.push({ score: institutionScore, weight: cfg.institutionNetBuy5d.weight });
+  const institutionScore = trendToScore(s.institutionTrend20d);
+  detail.institutionNetBuy20d = { label: cfg.institutionNetBuy20d.label, trend: s.institutionTrend20d, score: institutionScore };
+  items.push({ score: institutionScore, weight: cfg.institutionNetBuy20d.weight });

-  const shareholderScore = ...
-  detail.largeShareholderChange = { ... };
-  items.push({ score: shareholderScore, weight: cfg.largeShareholderChange.weight });
-
-  let buybackScore = null;
-  ...
-  detail.buybackOrRetirement = { ... };
-  items.push({ score: buybackScore, weight: cfg.buybackOrRetirement.weight });
+  // largeShareholderChange·buybackOrRetirement 제거 — 원자료 없음(2026-08-19 확인)

   return { score: weightedAverage(items), detail, coverage: coverageOf(items) };
 }
```

`trendToScore()` 자체는 무변경 — 5단계 분류(consistentBuy~consistentSell)를
그대로 쓴다.

## 4. `resolver.js` — 호출부 wiring (제안, 기존 dividendEps 패턴과 동일)

```js
// resolve() 시그니처에 supplyDemand 옵션 추가
function resolve({ ticker, corp, asOf, fundamentals = [], dividendEps, candles,
                   supplyDemand, price = null, sicCode = null, quality = null }) {
  ...
  const hasSupplyDemand = supplyDemand !== undefined;
  const sd = hasSupplyDemand ? supplyDemandFrom(supplyDemand, asOf) : null;
  ...
  if (hasSupplyDemand) stockData.supplyDemand = sd.values;
  ...
}
```
`candles`/`dividendEps`와 같은 원칙 — 호출부가 안 넘기면 `stockData.supplyDemand`
자체가 안 생긴다(빈 객체 아님). 기존 호출부(A5 프레임워크 테스트 등)는 영향 없음.

## 커버리지 재계산

```
기존 19칸 = fundamental(7) + valuation(4) + technical(4) + supplyDemand(4)
신규 17칸 = fundamental(7) + valuation(4, 여전히 미연결) + technical(4) + supplyDemand(2)

fundamental+technical+supplyDemand(2/2 채움) = 13/17 = 76.5%  ← 60% 게이트 통과
```
(2턴 전 언급한 "14/18=77.8%"는 개인축 포함 가정이었다 — Q2 기각으로 무효. 정정.)

## 아직 안 끝난 것 — Q3(대형주 한정)

**제안**: 지금은 전종목 동일 적용하되, 알려진 한계를 코드 주석과 provenance에
정직하게 남긴다(resolver.js가 `sectorNotPointInTime: true`를 남기는 것과 같은
패턴). 실제 시가총액 데이터가 없어(거래대금 proxy만 있음) 지금 조건부 로직을
넣는 건 검증 안 된 가정 위에 또 가정을 쌓는 것이다. 시총 매핑이 생기면 그때
재검토한다 — A4-RESEARCH-HANDOFF.md §9에 이미 "다음 확인 사항"으로 있다.

## 이 설계안이 아직 답 못한 것 (구현 전 확인 필요)

```
1  scoreSupplyDemand() 변경이 다른 어떤 코드에 영향을 주는지 전수 확인
   (grep "foreignTrend5d\|institutionTrend5d\|largeShareholderChange\|
   buybackOrRetirement" — 이 설계안에서는 안 함, 구현 착수 시 첫 단계)
2  supplyDemandFrom.js가 A4 원자료 로딩 성능(전 종목 매일 배치에서) —
   research probe는 35~120종목 규모였지 2,578종목 매일 운영 배치는 아직 안 재봄
3  trendFromWindow()가 정찰 스크립트 로직 그대로인데, 그 로직 자체가
   Codex/DeepSeek 독립 검증을 받은 적은 없음(A4 IC 분석은 raw 값 기준이었지
   이 5단계 분류 함수 자체를 검증한 게 아니다)
```

## 다음 단계 제안 (진행 여부는 GO 필요)

이 설계안을 그대로 실행하지 말고, **Codex에 🔴 설계 검토**로 먼저 보내는 걸
권합니다(AGENTS.md §2.2 — 🔴 결정의 설계·아키텍처 검토는 Codex 담당). 특히
"3번 miss — trendFromWindow 분류 함수 자체 미검증"이 걸립니다: A4 분석은
연속값(raw net-buy)의 IC를 쟀지, `trendFromWindow()`가 만드는 5단계 분류가
같은 강도의 신호를 보존하는지는 확인한 적이 없습니다. 이대로 구현하면 "IC가
강해서 붙였는데 분류 단계에서 신호가 죽어있더라"는 문제가 재발할 수 있습니다
(2턴 전 5일→20일 창에서 이미 한 번 겪었던 실수의 반복 형태).

설계 검토를 Codex에 먼저 보낼까요, 아니면 이 상태로 사용자 GO만 받고 진행할까요?

---

## ★ 2026-08-21 추가 — "3번 miss"의 절반(window 크기)을 OpenCode(DeepSeek)로 정찰

CLAUDE.md가 이 문서의 재개 조건으로 적어둔 "`trendFromWindow()`를 20일
창으로 바꿨을 때의 classification IC를 먼저 재는 것"을 실행했다.
`research/strategy-lab/slot_marginal_analysis_window{6,7,8,10,15,20}.js`로
window=5(기존 baseline)/6/7/8/10/15/20 전부 돌려 `base_inst`
(institutionTrend)·`base_foreign`(foreignTrend) config의 pooled Spearman
IC를 쟀다(production `scoreStock()` 그대로 사용, 슬롯 조합만 바꿈 — 이
설계안이 제안하는 `scoreSupplyDemand()` 변경과는 다른 임시 측정 방법).

**결과** (전체 표: `research/strategy-lab/findings/kr23-window-bisection.md`·
`kr23-window-comparison.md`):

```
base_inst d20 IC   window=5 -0.0011 → 6 -0.0007 → 7 +0.0009 → 8 +0.0038
                    → 10 +0.0017 → 15 +0.0091 → 20 +0.0092
                    부호 반전은 window=6과 7 사이. 단 전 구간 p≥0.29
                    (n=13213) — d20 단독 예측력은 통계적으로 유의한 적이
                    한 번도 없다.
base_inst d60/d120  전 window에서 양수. d120은 window=15(+0.0223)가
                    window=20(+0.0195)보다 오히려 높다 — window을 늘릴수록
                    단조 증가하지 않는다.
base_foreign d120   window=5(+0.0155) → 10(+0.0268) → 15(+0.0247) →
                    20(+0.0310) — 대체로 우상향하되 15에서 살짝 꺾인다.
```

**이 설계안에 대한 함의**:

1. **window=20 선택 자체는 나쁘지 않다** — base_foreign d120은 테스트한
   구간 중 window=20에서 최댓값이다. 다만 15와의 차이(±0.006)가 이
   프로젝트가 반복 경계해온 "노이즈 낀 점추정치로 정밀한 선택을 하지 않는다"
   원칙에 걸릴 만큼 작다 — window=20은 "합리적인 선택 중 하나"이지 "유일하게
   옳은 값"은 아니다.
2. **d20 단독(supplyDemand만으로 20일 앞 수익률을 맞추는 것)은 어느 window를
   써도 통계적으로 유의하지 않다.** d60·d120에서는 신호가 있다 — 이 축을
   넣는 근거는 "즉각 반응"이 아니라 "중장기(2~6개월) 추세 반영"으로 이해해야
   한다.
3. **"3번 miss"는 절반만 풀렸다.** window 크기가 classification IC에 미치는
   영향은 이제 실측이 있다. 하지만 원래 우려(A4의 raw 연속값 marginal IC
   분석과 `trendFromWindow()`의 5단계 분류가 같은 강도의 신호를 보존하는지)는
   **여전히 미검증**이다 — 이건 window 크기가 아니라 raw→classification
   변환 자체의 정보 손실을 재는 별개 실험이 필요하다.
4. **별개로 발견한 것 — standalone IC의 시드 의존성.** LOO marginal 실험을
   5개 시드(120종목 무작위 표본)로 반복한 결과(`research/strategy-lab/
   findings/slot-marginal-contribution/seed-robustness-comparison.md`),
   `base_foreign`의 **standalone** pooled IC 부호가 시드마다 다르게 나온다
   (seed1 전 구간 +, seed2 d60·d120 −, seed3 d20·d60 −/d120 ≈0, seed4·seed5
   전 구간 −). 이건 window 선택과 무관한 표본 변동성 문제로 보인다 — 120종목
   표본 하나로 "이 축이 예측력이 있다/없다"를 판단하는 게 위험하다는 신호다.
   같은 실험에서 `pbr`(A5-3 D4로 이제 막 열린 valuation 슬롯)의 LOO marginal
   ΔIC는 5개 시드 전부에서 1위였다 — supplyDemand 정교화보다 valuation
   연결이 더 크고 안정적인 레버일 가능성을 시사한다(교차 우선순위 판단은
   사용자 몫).

**결론**: 이 설계안의 "다음 단계 제안"(Codex 🔴 설계 검토 권고)은 그대로
유효하다 — window 크기 정찰은 그 검토가 다룰 질문 중 하나(raw vs
classification 정보 손실)를 대체하지 않는다. 사용자가 재개를 원하면
Codex 검토를 먼저 거치는 걸 여전히 권장한다.
