# A4-RESEARCH-HANDOFF.md — 다음 세션 인수인계

> 목적: 이 문서 하나로 A4 수급 연구 데이터셋의 상태와 다음 확인 사항을 파악한다.
> 정본이 아니다 — 원자료·정책·검증 원본(`data/backfill/supplyDemand/a4/*`,
> `config/policies/supplyDemand.v1.json`, probe 스크립트 결과)이 정본이다.
> 작성: 2026-08-19 (독립 실행 기반 검증, DeepSeek — 사용자 확인, Claude 검토·통합)

## 1. 조사 내용

A4(종목별 일별 수급) 원자료를 연구용 데이터셋으로 가공하고, 수급 파생 feature의
forward return 예측력을 cross-sectional로 측정했다. 스트리밍(연도별 gz 파일 1회
읽기)으로 540만 행을 컨텍스트에 넣지 않고 처리했다.

- 원자료 존재·스키마 재확인: 12 카테고리(개인·금융투자·기타금융·기타법인·기타외국인·
  보험·사모·연기금·외국인·은행·투신·전체) × 매수/매도 × 금액/수량.
- KRX 시장 청산 항등식(`전체 매수 == 전체 매도`) 전량 재검증.
- 수급 파생 feature: 외국인/기관/개인 순매수 1/5/20d rolling 합, 거래대금 대비
  20d 비율, log거래대금. 전부 PIT(미래 미사용).
- forward return d20/d60/d120 (A2a adjusted close 기준).
- 분석: IC/Rank IC, 10분위, 연도별, 규모별(거래대금 proxy), 조합, 결측률.

## 2. 사용 데이터

| 데이터 | 위치 | 용도 |
|---|---|---|
| A4 원자료 | `data/backfill/supplyDemand/a4/{2016..2026}.jsonl.gz` | 수급 netbuy 파생 |
| A4 finalize 검증 | `data/backfill/supplyDemand/a4/_diagnostics.json` | 항등식·acceptance 대조 |
| A2a 가격 | `data/backfill/price/a2a/*.jsonl.gz` (adjusted) | close, forward return |
| A2a 정책 | `config/policies/price.v1.json` (PR-1.5/1.6, adjusted) | 수정주가 확인 |
| A4 정책 | `config/policies/supplyDemand.v1.json` (SD-1.0) | 수집·카테고리 정의 |
| 기존 검증 | `scratch-a4-supplydemand-vertical-slice.json`, `scratch-a4-runbacktest-comparison.json` | §7 대조 |

## 3. 데이터셋 위치

`research/strategy-lab/data/a4/`

- `a4-research-dataset.parquet` — 5,348,454행, 2,558종목, 2016-01-04~2026-08-03.
  컬럼: ticker, date, foreign_net, inst_net, indiv_net, net_{11개 카테고리},
  total_amount, total_volume, close, fwd_d20/60/120, foreign/inst/indiv_nb_{1d,5d,20d},
  foreign/inst/indiv_nb20_ratio, log_total_amount.
- `a4-feature-summary.json` — 컬럼 정의·통계·결측·계산 불가 항목.
- `a4-data-quality.json` — 재검증 결과·제외 규칙.
- `a4-analysis-results.json` — 분석 결과 전량.
- `README.md` — 데이터셋 사용 안내.
- 빌드/분석 스크립트: `../build_a4_research_dataset.py`, `../analyze_a4_research.py`.

## 4. 핵심 검증·연구 결과

### 검증 (확정)
- **KRX 항등식 재검증**: `buyAmount['전체'] == sellAmount['전체']` 전 5,409,687행에서
  0 위반. 원자료 finalize(`_diagnostics.json`)와 일치.
- **카테고리 키 집합**: 전 레코드 1종 (동일 스키마).
- **A2a 조인**: 2,578종목 → 2,558종목 매핑. 20종목은 A2a close 부재로 제외.
- **PIT**: rolling feature는 날짜 오름차순 누적 — 미래 정보 미사용. forward는 t 이후
  거래일 기준.
- **A2a 기간 한계**: 2026-08-03 (A4는 08-14) — 패널 말미 forward NaN은 의도적.

### 연구 결과 (잠정치, 방향성 확인용)
- **기관 20d 순매수**: d60 IC +0.011 (t=13.5), d120 IC +0.022 (t=25.2) — 가장 강한 양의
  시그널. 단 d20은 +0.004로 약함.
- **외국인 20d 순매수**: d20 +0.004 / d60 +0.009 / d120 +0.012 — 장기로 갈수록 강해짐.
- **개인 20d 순매수**: d20 -0.002 / d60 -0.010 / d120 -0.022 — 음의 시그널. 개인이
  과매수하는 종목의 장기 수익률이 낮다.
- **규모 의존**: 거래대금 3분위 기준 대형(T3)에서만 외국인/기관 순매수가 양의 IC
  (+0.013/+0.010), 소형(T1)은 음수(-0.013/-0.008).
- **연도 불안정**: 개인 음의 IC는 2019년 이후 정착, 외국인·기관 양의 IC는
  최근연도로 갈수록 강화(2026: 기관 +0.058, 개인 -0.068). 2016~2018에는 기관이
  음수였던 연도도 존재 → 고정 파라미터 운영 위험.
- **Decile**: D5(중앙) 최고, 양극단 하락의 뒤집힌 U. "순매수 상위를 사면 좋다"는
  단순 규칙은 미지지.
- **조합**: 외국인&기관 동시 순매수 vs 동시 순매도 d60 평균 +0.021 vs +0.018 — 구분력 미미.
- **거래대금 비율 feature**: 순매수 금액과 부호 반대 — 소형·저유동성 극단값 영향
  의심. 추가 검증 전 운영 후보 아님.

## 5. 확정 사실

- A4 원자료는 실제 존재하고 완결됐다 (SD-1.0, KRX/pykrx, 2016-01-04~2026-08-14,
  5,409,687행, 2,578종목, finalize acceptancePassed=true).
- 순매수는 원자료에 없고 매수-매도로 유도한다 (항등식 12/12 카테고리 성립 — 전체 매수=매도 0 위반).
- KIS(inquire-investor)는 고정 ~30거래일 창·날짜 파라미터 없음 → 백필 불가로 기각,
  KRX가 유일한 백필 경로 (supplyDemand.v1.json note, 2026-08-17 세션 실측).
- A2a는 adjusted(수정주가) — 이 데이터셋의 close·forward return은 전부 adjusted 기준.
- A4 5일 창 join 100%, PIT 위반 0, 35종목×553일 vertical slice 성립 (기존 probe,
  scratch-a4-supplydemand-vertical-slice.json).
- runBacktest 비교 (기존 probe, scratch-a4-runbacktest-comparison.json):
  baseline(재무+기술) eligible 0/19,355 (INSUFFICIENT_COVERAGE),
  +supplyDemand(재무+기술+수급) eligible 14,803/19,355 (76.5%). 평균 IC 약 +0.004,
  등급 단조성 미충족, A등급이 d60(-3.26%)·d120(-0.95%)에서 최하위.
- KR_4AXIS 트랙은 **보류** (세션인수인계-2026-08-18-b.md) — A5-3(valuation)이
  resolver.js:170-196에 미연결이라 valuation 미기여. "KR_3AXIS/KR_4AXIS" 명칭 대신
  "baseline/[+supplyDemand]" 명칭을 사용.

## 6. 가설 (검증 대상)

- H1: **기관 20d 순매수 → 60~120거래일 양의 forward return** — 실측 IC +0.011/+0.022,
  t값 높음. 지지.
- H2: **개인 20d 순매수 → 음의 forward return** — 실측 -0.010/-0.022. 지지.
- H3: **수급 시그널은 대형주에서만 유효** — 실측 대형만 양의 IC. 지지.
- H4: **관계의 시간 불안정** — 연도별 IC 변동이 크고 최근연도로 부호가 강화되는
  추세. "강한 시그널"이라기보다 "시장 국면 의존"일 수 있음. 지지.
- H5: **수급 feature 단독 전략은 부적합** — decile 뒤집힌 U, 조합 구분력 미미,
  t=0부터 순수 buy 규칙은 위험. 개별 종목 alpha로는 약함.

## 7. 기존 결과와의 관계

- **일치**: runBacktest 평균 IC ≈ +0.004 (방향성 약하게 양) — 이 데이터셋의 외국인·
  기관 20d IC(+0.004~+0.022)와 부호 일치. d20 IC +0.01(기존) vs +0.004(본 데이터셋)
  는 feature 정의(기존: 5일 추세 분류 규칙; 본: 20d 합계)와 IC 계산 대상(기존: 등급
  vs return; 본: raw feature vs return)이 달라 수치 직접 비교 불가 — 부호·크기
  자리수만 일치.
- **일치**: d60/d120 IC가 0에 수렴(기존 d60 0.001/d120 0)한다는 점은 본 데이터셋의
  기관·외국인 20d가 d60~d120에서 유의미한 양의 IC를 갖는 것과 **부분 불일치** —
  기존 runBacktest는 35종목·19,355셀만(본 5.3M셀)이고 feature가 달라 표본·정의
  차이로 보임. "불일치"로 보고, 다음 세션에서 같은 정의로 재대조 권장.
- **한계**: 기존 vertical slice·runBacktest 결과는 35종목 정찰용 — 본 데이터셋이
  전량으로 더 큰 표본. 운영 결정 기준으로 삼지 않는다.

## 8. A5-3으로 말할 수 없는 것 (본 데이터셋의 한계)

- **시가총액·밸류에이션 관련 결론 불가** — A1a 유니버스 시총 매핑, PER/PBR 등은
  미연결. 규모 결론은 거래대금 proxy 기준 잠정치다.
- **운영(점수 반영) 여부·가중치·threshold 결정 불가** — 이 데이터셋은 방향성 확인
  용. SD-1.0 정책·KR_4AXIS 승격은 별도 🔴 승인 영역.
- **외국인 보유율·공매도·주당 수급** 결론 불가 — 원자료 부재.
- **2026-08-04 이후 forward return** 결론 불가 — A2a 수집 한계.
- **상장폐지 편향 정량화** 불가 — 전량 panel이지만 A2a 미커버 20종목 제외분과
  survivorship 규모는 A2b/A1b 병합이 필요.

## 9. 다음 확인 사항 (우선순위 순)

1. **H1~H5 재검증**: 같은 parquet에서 각 feature에 대해 (a) 일별 IC의 분포(중앙값·
   이상치), (b) 월별·국면별(DOWN/UP, regime 스크립트 재사용) 안정성, (c) 대형주
   서브셋으로 한정한 decile 다시 보기 — 뒤집힌 U가 대형에서도 유지되는지.
2. **기존 runBacktest와 동일 정의 재대조**: 5일 추세 분류 규칙을 같은 패널에
   재현해 IC 수치가 기존(scratch)과 같은지 — §7의 부분 불일치 해소.
3. **survivorship**: A2b/A1b 병합 패널로 기관 20d IC 재계산 — 상장폐지 종목 포함 시
   유지되는지.
4. **A5-3 연결 여부 결정** (🔴, 사용자): valuation을 resolver에 연결하면
   KR_4AXIS로 승격 가능 — 별도 승인 필요.
5. **비율 feature(거래대금 대비)의 극단값 원인** — 소형·저유동성 분리 후 재검증.
6. **보유율·공매도 데이터 획득 가능성** — docs/operations/data-source-availability.md
   기준 차단 상태. 획득 시 확장 여부는 별도 결정.