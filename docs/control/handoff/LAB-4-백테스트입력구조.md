# LAB-4 — 백테스트 입력 구조와 basis 시계열

```
발행    2026-08-11 · Claude
Owner   AI-Lab
우선    5순위 — 급하지 않다. 다만 이 결과가 나머지 실험이 언제 열리는지를 정한다
형식    docs/AI협업-업무분담.md §3
```

## 목적

두 가지다.

```
① 전략 실험이 언제 열리는지 실험실이 스스로 확인한다
② SB-1.0 의 축 basis 가 23일 동안 흔들리는지 본다
```

①은 자기 일정을 재는 작업이다. `docs/AI협업-업무분담.md` §2.1이 factor·weight·threshold
민감도를 표본 조건까지 보류했고, 그 조건이 언제 참이 되는지는 아무도 안 재고 있다.

②는 `SB-1.0`이 선언한 모델이 실제 데이터와 맞는지 보는 것이다. 선언은 `KR_4AXIS`·
`KR_3AXIS`·`US_3AXIS` 셋인데, 23일치 스냅샷에서 관측되는 basis가 그 셋뿐인지는
2026-08-10 하루만 확인됐다.

## 현재 상태 — 실측

```
이력          docs/data/history/  23일 (2026-07-12 ~ 08-10) · 스냅샷 2,109건
              20종목/일로 시작해 08-07부터 143종목/일

계산 가능한 표본   d20  24건    ← MIN_SAMPLE 30 미만
                  d60   0건
                  d120  0건

docs/data/backtest.json   status: "insufficient_history" (2026-08-09 기준)

2026-08-10 하루의 basis 분포
  KR  fundamental+valuation+technical+supplyDemand   99건
  KR  supplyDemand+technical                          1건
  US  fundamental+valuation+technical                43건
```

## 입력

```
docs/data/history/*.json
  항목  ticker · name · market · close · stockData
  stockData  fundamental · valuation · technical · supplyDemand

조인 로직의 정본
scripts/backtest-report.js:78~103
  HORIZON_DAYS = { d20: 28, d60: 84, d120: 168 }   거래일 → 달력일 근사 (7/5배)
  findSnapshotOnOrAfter(days, addDays(day.date, calDays)) 로 미래 스냅샷을 찾는다
  forwardReturns 는 저장돼 있지 않고 여기서 계산된다

lib/backtester.js       표본 편입 계약 · classifyBase · byHorizon
config/policies/scoreBasis.v1.json   SB-1.0 모델 선언
```

**`forwardReturns`를 새로 구현하지 않는다.** 위 로직을 그대로 쓴다 — 다시 구현하면
백테스트가 검증하는 것이 운영이 쓰는 그 계산이 아니게 된다.

## 기대 출력

```
1  d20 표본의 일자별 누적 곡선과 30 돌파 예상 시점
   → 143종목/일 스냅샷은 08-07 부터다. 그 구간이 성숙하는 시점을 따로 표시한다
2  d60 · d120 이 처음 계산되는 시점
3  날짜별 축 basis 분포 (23일 전체)
   → SB-1.0 이 선언한 셋 밖의 basis 가 관측되는가
4  같은 종목의 basis 가 날짜에 따라 바뀌는가
   → 바뀌면 그 종목은 시계열 안에서 모델이 바뀐 것이다
5  close 가 없거나 미래 스냅샷에서 사라진 종목의 수
   → 편입에서 조용히 빠지는 경로다
```

4번이 이 과제의 값이다. **basis가 날짜에 따라 바뀌면 그 종목의 시계열 IC는 한 모델의
예측력이 아니다.** SB-1.0은 그 문제를 하루 단위 산출물에서 다뤘지 시계열에서는 아직 안 봤다.

## 제약

```
★ IC · 등급 성과 · 승률 · 민감도를 계산하지 않는다. 표본이 24건이다
전략 우열을 판단하지 않는다
HORIZON_DAYS 나 MIN_SAMPLE 을 바꾸자고 제안하지 않는다
docs/data/ 에 쓰지 않는다 — 그 경로의 Writer 는 GitHub Actions 다
```

## 관련 계약

```
config/policies/scoreBasis.v1.json   SB-1.0
docs/A5-1.0-입출력계약.md            §5.1 게이트 4 결정
lib/backtester.js                    표본 편입 계약 (2026-08-11)
docs/AI협업-업무분담.md              §2.1 표본 대기 조건
```

## 관련 commit

```
b7a4c33   A5 게이트4 · SB-1.0 · basis 판정
82e796e   백테스트 표본 편입 계약
```

## 검증 방법

```
d20 = 24 · d60 = 0 · d120 = 0 을 먼저 재현한다. 재현되면 로직이 맞다
basis 분포의 2026-08-10 행이 위 실측(99/1/43)과 일치하는지 대조한다
```

## 주의사항

```
★ 이 결과로 전략 판단을 하지 않는다. 언제 판단할 수 있는지를 재는 작업이다

★ 30 돌파 시점은 추정이다. 스냅샷 종목 수가 늘어난 이력이 있어 단순 외삽이 어긋난다.
  '확인된 사실 / 추정'을 갈라 적는다(업무분담 §4)

★ backtest.json 이 status:"insufficient_history" 인 동안은 byHorizon 필드 자체가
  생성되지 않는다 — backtest-report.js:135 가 runBacktest 를 부르기 전에 조기 반환한다.
  그래서 해제 조건이 두 단이다
```

## 산출물

`docs/verification/`. `docs/data/` · `data/backfill/**/manifest/` 에 쓰지 않는다.
