---
track: kr
factor: v5-divergence
date: 2026-08-22
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["foreign_nb_5d_positive", "inst_nb_5d_negative", "t_plus_1_open"]
reason: "V5(외국인 순매수+기관 순매도 5일) 사전 감사 - 원자료·연구parquet(A4 foreign_nb_5d/inst_nb_5d)·PIT(t+1 open) 모두 충족(A), 설계 결정 4건(B-1~4)은 사람 판단 대기"
---
# V5 사전 감사 — 외국인 순매수 + 기관 순매도 다이버전스 (5거래일)

> 조사만 수행, 코드 미작성. 작성 2026-08-22. 가설은 [OBSERVED] 그대로: 최근 5거래일
> 누적 수급에서 외국인 순매수 + 기관 순매도(또는 반대 방향).

## 결론: **A (지금 데이터로 바로 가능)** — 단 설계 결정 포인트 4개(B)가 붙는다

---

## 1. 원자료 존재·필드명 — 확인됨

- 위치: `data/backfill/supplyDemand/a4/{2016..2026}.jsonl.gz` (+`_diagnostics.json`)
- 정책: `config/policies/supplyDemand.v1.json` (SD-1.0, KRX via pykrx, 유일 백필 경로)
- 규모: 5,409,687행 / 2,578종목 / 2016-01-04~2026-08-14, `acceptancePassed=true`,
  unresolved=0, marketClearingViolations=0
- 행 필드: `ticker`, `date`, `buyAmount`, `sellAmount`, `buyVolume`, `sellVolume`
  — 금액/수량 × 매수/매도 4개 객체이고 각 객체의 키가 투자자구분 12종:
  개인·금융투자·기타금융·기타법인·기타외국인·보험·사모·연기금·**외국인**·은행·투신·전체
- **순매수 필드는 없다**(교훈75 파생값 미저장). 순매수 = buyAmount[cat] − sellAmount[cat]
  으로 유도. 항등식(매수−매도 카테고리 합 = 0) 전건 검증 통과.
- "외국인" 단일 키는 있으나("외국인"+"기타외국인" 분리), **"기관" 단일 키는 없다** —
  하위 카테고리 합으로 유도해야 한다.

## 2. "5거래일 누적" 구조 — 가능, 이미 계산된 것도 있다

- 원자료 정렬 `[date, ticker]`, 거래일(A0.5 캘린더)별 (ticker,date) 1행.
- **연구용 parquet가 이미 존재**: `research/strategy-lab/data/a4/a4-research-dataset.parquet`
  (5,348,454행 / 2,558종목 / ~2026-08-03) — `foreign_nb_5d`·`inst_nb_5d`·`indiv_nb_5d`
  컬럼에 ticker별 날짜 오름차순 rolling(5, min_periods=1).sum() 이 계산돼 있다
  (`build_a4_research_dataset.py`). V5 검증은 이 패널에서 바로 가능.
- 결측 처리: 보간 없음(NaN 보존). rolling은 "존재하는 행" 기준이라 거래정지 등으로
  행이 비면 창이 실제 5거래일보다 길게 뻗고, 워밍업 구간(min_periods=1)은 부분합.
  → V5에서 창을 어떻게 정의할지는 설계 결정(B-3).
- A2a close 조인 시 20종목 제외(2,558/2,578), 가격 말단 2026-08-03.

## 3. PIT — 엔진 관례 하에서 안전

- 데이터 성격: KRX 일별 투자자 집계는 **해당 거래일 장마감 후 확정·발표**되는 값이다.
  즉 t일 수급은 t일 장중/종가 시점에 "즉시" 알 수 있는 정보가 아니라 같은 날 저녁에
  확정된다. 같은 날 종가 체결을 가정하면 경계선상, 다음날 체결이면 안전.
- 이 저장소의 실행 계약은 **signal t → 다음 거래일 open 체결**
  (`engine/execution/executor.py`: `order_date = calendar.next_session(signal_date)`,
  entry at next open). 따라서 t일 수급으로 신호를 만들어 t+1 open에 진입하는 V5는
  PIT 위반이 아니다.
- feature 계산 PIT도 구조적으로 방어돼 있다(`engine/data/pit.py` PITBars,
  rolling backward-only). 결론: **t+1 open 진입 관례를 지키면 PIT 문제 없음.**

## 4. 기존 전략의 수급 feature 사용 — 둘 다 없음

- `strategies/5dc_v1a_p/rule.py`: Bollinger+CCI+ATR (가격만).
- `strategies/trend_breakout_v1/rule.py`: Donchian+ATR (가격만).
- 수급은 별개 트랙에서만 사용됐다: ① a4 연구 데이터셋 IC/decile/조합 분석
  (`data/a4/a4-analysis-results.json`) ② production runBacktest "+supplyDemand"
  probe 35종목 슬라이스(`scratch-a4-runbacktest-comparison.json`).
- **V5와 부분적으로 겹치는 기존 결과(20d 창, d60 기준)**:
  - 조합: bothBuy +0.0206(n=107.7만) / bothSell +0.0180(n=135.8만) /
    **foreignOnly(외국인 매수+기관 매도, V5 방향) +0.0219(n=134.5만)** /
    instOnly(반대 방향) +0.0189(n=135.8만) — 20d 창 기준으로는 bothBuy와 foreignOnly
    구분력이 미미했고, 이는 5d 창 V5에 대한 참고치일 뿐 동일 스펙 검증은 아니다.
  - 5d 단독 IC: foreign_nb_5d d20 +0.005(t=5.5)/d60 +0.002,
    inst_nb_5d **d20 −0.002(t=−2.4)**/d60 +0.003/d120 +0.008.
    기관 5d는 초단기(d20)에서 음의 IC — 역방향 다이버전스 해석 시 주의 포인트.

## B. 실행 전 설계 결정 필요 목록 (Claude·사용자 판단 영역)

1. **B-1 "기관" 정의**: KRX 표준 기관계(7카테고리, 기타법인 제외) vs 기존 a4
   데이터셋 정의(8개 — `build_a4_research_dataset.py`는 기타법인을 기관에 포함).
   V5가 어느 쪽인지 [OBSERVED] 규칙 기준으로 확정 필요.
2. **B-2 임계값**: "순매수/순매도"를 부호(>0/<0)만으로 볼지, 금액 규모 임계를 둘지.
   기존 decile은 뒤집힌 U(양극단 약함)라 규모 임계 도입 여부가 민감하다.
3. **B-3 창 정의**: rolling(5) 행 기준(부분합 허용) vs A0.5 캘린더 기준 5거래일 강제
   (거래정지 시 NaN 처리).
4. **B-4 보유 기간**: V5가 이벤트성 단기 신호라면 d60/d120 대신 d20 이하 재채점 필요
   — 기관 5d의 d20 음의 IC(§4)가 반대 방향 가설과 충돌할 수 있어 먼저 확인 가치.

## C. 데이터 없음 — 해당 없음

V5에 필요한 외국인/기관 일별 순매수는 모두 존재한다. (참고: 외국인 보유율·공매도
잔고·시가총액 매핑은 원자료 부재 — V5와 직접 무관.)
