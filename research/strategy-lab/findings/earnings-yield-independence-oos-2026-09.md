---
track: kr
factor: earnings-yield-independence-oos
date: 2026-09-06
verdict: HOLD
criteria_version: v1
conditions: ["earnings_yield=1/per(per>0, PIT)", "size=dv20_log(log 20일평균 거래대금)", "pbr=panel PBR(순자산가치 스타일)", "residualization=TRAIN고정(월별계수 중앙값) vs 월별(Fama-MacBeth) 병기", "TRAIN<=2022-06-30/VALID<=2024-01-01/TEST>2024-01-01", "dv20>=1e8", "top_decile"]
reason: >-
  EY는 Size·PBR·업종 어느 축에도 독립적이지 못하다(Size corr -0.25, PBR corr -0.59~-0.65,
  업종집중 상위3개 ~26%). 그러나 잔차화 후에도 TEST에서 여전히 유의한 알파가 남는다 —
  Size 잔차화 TEST IC t=3.53(월별)/3.52(TRAIN고정)로 거의 보존, PBR 잔차화 t=3.50/3.72,
  PBR+Size 잔차화 t=3.62/3.71, 업종중립(sectorRelEY) TEST IC t=3.33. raw EY의 구간별 TEST
  CAGR는 10.79%·Sharpe 0.653(n=31·IC t=3.64)이며 Size 잔차화로도 CAGR 11.24% 유지 — Size는
  EY 강도를 거의 깎지 않는다. 그러나 PBR 잔차화 시 TEST CAGR가 3~4%대로 크게 축소(Sharpe
  0.25~0.33)되어 EY 롱수익의 상당 부분이 순자산가치 스타일과 겹친다. 업종중립도 TEST CAGR를
  절반 수준(6.2%)으로 깎는다. 연도별 편차가 커(TRAIN 내 2022 -23.75%) 전체기간 net CAGR는
  2.68%에 불과, 비용 50bps 왕복 시 0.25%·65bps에서 -1.55%로 비용에 취약. 결론: EY는 PBR·업종
  too로는 사라지지 않는 잔차 IC(테스트 t≈3.5~3.7)를 가지되, 포트 수준에서는 Size는 무해·
  PBR/업종은 재료의 일부만 남기는 퇴색 구조 — 단독 성과 상한을 보수적으로 재평가.
cagr: 0.1079
sharpe: 0.653
mdd: -0.1444
win_rate: 0.548
n: 31
t_stat: 3.64
---

# Earning Yield 독립성 OOS — Size/PBR/업종 잔차화와 비용·연도 robustness 검증

- 검증일: 2026-09-06
- 스크립트: `research/strategy-lab/07_ey_independence_oos.py`
- 산출물: `reports/2026-09-06-ey-independence-oos/ey-independence-oos.json`
- **최종 판정: HOLD** (수용도 절반 — SIZE 무해, PBR/업종 잔차화 시 유의하지만 크게 퇴색)

## 1. 방법

- `factor_discovery_kr.py`의 base 규약 재사용(A4 수정주가 close·거래대금, PIT
  valuation-panel `per` → `earnings_yield`=1/per(per>0), fwd1m, 유동성 dv20≥1억원,
  top-decile EW 월 리밸). 유니버스 = liquid + EY 유효 표본 **83,088 obs / 126개월**
  (전체 EY 커버리지. 이전 complement 실험의 EY∩LOWMOM 축소 유니버스와 다름).
- 기간 분할: TRAIN ≤2022-06-30, VALID ≤2024-01-01, TEST 이후.
- 잔차화 2종 병기: **(1) TRAIN-고정 직교화**(설계 지시 — TRAIN 월별 컨트롤 계수의
  중앙값을 전월에 고정 적용)와 **(2) 월별(Fama-MacBeth) 직교화**, 둘 다 rank 변환·
  OLS lstsq. 결과는 두 방식이 거의 동일 → 잔차화 방법 민감도 없음.
- 컨트롤: size=`dv20_log`, value=`pbr` 패널 rank. 조합: Size / PBR / Size+PBR.
- 업종: `sector`(A1a 현재 분류, 엄밀한 PIT 아님 — 한계), 업종중립=`sector_rel_earnings_yield`
  (섹터 내 pct-rank, 패널 기구축) 재사용.
- 비용: top-decile 월 EW 포트에 `cost_bps/10000` 월 차감(전량 재편 가정).
  baseline 30bps 왕복, 민감도 50/65bps 왕복.
- 지표: raw/잔차화/업종중립 각각의 top-decile net CAGR·Sharpe·MDD·WINRATE·n·IC t.

> **★ 유니버스 정합성 주의** — 이전 complement 실험(`07_ey_mom_complement_oos.py`)의
> EY 단독 TEST는 CAGR 13.32%·Sharpe 0.780·n=32·IC t=3.55로 보고했다. 그것은 EY **&**
> LOWMOM60 동시 유효 표본으로 축소한 유니버스에서 낸 값이다. 본 실험은 LOWMOM 결합 없이
> **전체 EY 커버리지 유니버스**에서 재측정한 것으로 TEST CAGR 10.79%·Sharpe 0.653·n=31·
> IC t=3.64를 준다. 두 수치의 차이는 유니버스 선택의 결과이며, 13.32%는 LOWMOM 결합 표본에
> 국한된 값이다. **EY 단독의 기준 유니버스 수치로는 본 실험의 10.79%가 정본** —— 이 관측만으로
> 낙관/비관을 고르지 않는다(§4 관측 원칙).

## 2. 결과

### 2.1 base decile (raw EY, 전 유니버스)

| 구간 | n | 개월 | slope | IC t | IC mean | topDec net CAGR | Sharpe | MDD | mono ratio |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| ALL | 83,088 | 124 | 0.867 | 6.10 | 0.0563 | 2.68% | 0.232 | -40.0% | 0.556 |
| TRAIN | 46,063 | 75 | 0.745 | 4.07 | 0.0455 | -0.17% | 0.106 | -40.0% | 0.667 |
| VALID | 13,713 | 18 | 0.576 | 3.31 | 0.0541 | 1.32% | 0.163 | -13.3% | 0.667 |
| **TEST** | **23,312** | **31** | **0.758** | **3.64** | **0.0838** | **10.79%** | **0.653** | **-14.4%** | **0.667** |

### 2.2 Size 독립성 — CLEAN PASS

- raw EY와 size 교차단면 상관: corr **-0.25** (TEST t=-31.6) — 유의하지만 약한 음상관.
- Size 잔차화 후 TEST 잔차 IC: **0.068 (월별 t=3.53) / 0.070 (TRAIN고정 t=3.52)** —
  raw TEST(0.084) 대비 소폭 감소, t는 3.64→3.5로 거의 유지. TRAIN도 t=2.43~2.45로 유의.
- top-decile net TEST: raw 10.79% → Size 잔차 11.24%(월별·TRAIN고정 동일), Sharpe
  0.653→0.635/0.639. **Size는 EY 강도를 거의 훼손하지 않는다.** TRAIN고정과 월별 방식이
  사실상 같아 방법 민감도 없음.

### 2.3 PBR(가치) 독립성 — IC는 생존, 포트 성과는 크게 퇴색

- raw EY와 PBR 교차단면 상관: corr **-0.59~-0.65** (TEST -0.654, t=-166) — 강한 음상관.
- PBR 잔차화 TEST 잔차 IC: 0.042(월별 t=3.50) / 0.052(TRAIN고정 t=3.72) — **여전히 유의**.
- 그러나 top-decile net TEST CAGR는 raw 10.79% → **3.89%(월별)/2.93%**(TRAIN고정),
  Sharpe 0.30/0.25. **EY 롱수익의 상당 부분이 PBR 순자산가치 스타일과 겹친다.**
- Size+PBR 동시 잔차화: TEST IC t=3.62/3.71(유의 보존), CAGR 4.47%/4.39%, Sharpe 0.33 —
  PBR 단독과 유사(Size 추가로 더 나아지지 않음).

### 2.4 업종 독립성 — 집중되어 있으나 업종만은 아니다

- TEST top-decile 집중: 83개 섹터, 상위3 섹터(자동차 부품, 기타 금융, 1차 철강)가
  ~26% 차지(9.7%+8.3%+7.7%) — 특정 섹터 편중 실재.
- 업종중립(sector_rel_earnings_yield, 섹터 내 pct-rank) TEST: IC 0.0625(t=3.33, 유의),
  top-decile CAGR 6.22%·Sharpe 0.451. **신호가 순수 섹터 베팅은 아니다(잔차 IC 유의)**
  하지만 당연히도 raw(10.08%·0.618) 대비 TEST 성과가 절반으로 깎인다 → 롱수익의 일부는
  섹터 틸트에서 나온다.

### 2.5 연도별 robustness — 강하지만 뭉침(lumpy)

전체기간 top-decile net 연도별 CAGR(2026은 연중 7개월):
2016 +11.7 / 2017 +0.1 / **2018 -15.9** / 2019 +13.1 / 2020 +4.9 / 2021 +17.2 /
**2022 -23.8** / 2023 +4.0 / **2024 -10.9** / 2025 +23.0 / 2026 +34.5.
- 음의 해 3개(2018·2022·2024), 그중 2022가 -23.8%로 TRAIN 전체를 끌어내려 ALL-period
  net CAGR 2.68%에 그친다. 6~8개월 양수(매년)로 꾸준하진 않다.
- 분할 경계 이후(VALID·TEST)는 2022 이후 전부 양수 — TRAIN 내 부진 기간은 검증에서
  제외되므로 OOS 관점에선 안정적으로 보이지만, 이는 분할 경계가 부진 해를 TRAIN에 밀어
  넣은 결과로도 읽힌다(절대 낙관 근거로 쓰지 않음).

### 2.6 비용 민감도 — 30bps에서 겨우 유지, 50bps부터 소멸

| 비용(왕복) | ALL net CAGR | Sharpe | MDD | meanM |
|---:|---:|---:|---:|---:|
| 30bps | 2.68% | 0.232 | -40.0% | +0.410% |
| 50bps | 0.25% | 0.119 | -43.0% | +0.210% |
| 65bps | **-1.55%** | 0.034 | -46.7% | +0.060% |

top-decile 월 전량 재편(max turnover) 가정이므로 30bps에서도 ALL net가 2.68%로 낮다.
50bps 왕복이면 사실상 0, 65bps면 음수. **실거래 비용·슬리피지를 보수적으로 잡으면
단독 top-decile 순수익 마진이 얇다.**

## 3. 설계 판정 관점별 평가

1. **기간 OOS 성과가 유지되는가 — IC는 유지, 개월 수 축소(TEST 31개월).** TEST IC
   t=3.64(n=31)로 유의, CAGR 10.79%. 다만 전체기간 net(2.68%)이 크게 낮은 것은 TRAIN 내
   2022 탱크 때문이며, 비용 50bps 이상에서 소멸.
2. **Size 중복 — 아니다(CLEAN PASS).** corr -0.25, Size 잔차화 후에도 TEST IC
   t≈3.52~3.53·CAGR 11.24%로 거의 그대로. EY의 알파는 시총 편향이 아니다.
3. **PBR 가치 중복 — 부분적(HOLD 핵심).** 잔차 IC는 TEST에서 유의(t=3.50/3.72)하지만
   포트 성과(Test CAGR)가 10.8%→3~4%로 1/3 이하로 줄어든다. **EY는 순자산가치 스타일
   너머의 유의한 잔차 신호를 갖되, 그 '있는 그대로의' 롱 수익 대부분은 PBR과 공유.**
4. **업종 중복 — 부분적.** top-decile 섹터 집중(상위3 ~26%)이 실재하고 업종중립하면 TEST
   성과가 절반(6.2%)으로 깎인다. 그러나 업종중립 IC t=3.33로 유의 — 섹터 틸트만으로 설명
   안 되는 잔차 알파도 존재.
5. **비용 — 취약.** top-decile 전량 재편 가정하 30bps 왕복에서 ALL net 2.68%, 50bps에서
   0.25%로 마진이 거의 없다. 단독 전략으로 상용화하려면 turnover 줄이는 설계가 전제돼야 함.

## 4. 판정

**HOLD.** EY는 Size·PBR·업종에 독립적인 완전 독립 알파가 **아니며**, 그중 PBR 및 업종과는
포트 성과가 크게 겹친다. 그러나 순수 잔차화·업종중립 후에도 TEST에서 **유의한 잔차 IC
(t≈3.5~3.7)** 가 남는다:

- **Size 잔차화 CLEAN PASS** — 잔차 IC TEST t=3.5, CAGR 11.24% 유지. 시총 편향 아님.
- **PBR 잔차화로 포트 성과 퇴색**(TEST CAGR 10.8%→3~4%, Sharpe 0.25~0.33) — 그러나 잔차
  IC t=3.5~3.7 유의 유지 → **EY는 PBR 너머의 정보를 가지되 그 크기는 포트 단위로 작다.**
- **업종중립으로도 유의**(TEST IC t=3.33)하되 성과 절반 — 섹터 틸트와 잔차 알파의 혼합.
- **연도 분산·비용 취약** — 전체기간 net 2.68%(30bps), 50bps에서 0.25%, 2022/2024 음수.

**이 결론이 의미하는 것(관측, 채택 판단 아님):** EY를 '순수 독립·무비용 알파'로 승격하기엔
근거가 부족하다. 다만 PBR·업종·Size와 완전 동일한 신호도 아니며, 남는 잔차 IC는 TEST에서
t≈3.5 이상으로 반복 확인된다 — **복합 가치 조합(EY+PBR 등) 내 한 축으로는 살아있다는 방향**의
관측이며, 단독 top-decile 라인은 비용·퇴색 고려 시 상한을 보수적으로 잡아야 한다.
REJECT(사용 불가)는 아니다 — 유의 잔차 IC가 재현되므로 '기각'보다 '성과 상한 하향'이 맞다.

## 5. 한계

- size proxy는 `dv20_log`(시가총액 비계산 프로젝트 표준) — 시가총액 잔차화와는 다른 정의.
- `sector`는 A1a 현재 분류로 엄밀한 PIT가 아님(분류 변경 반영 지연 가능).
- top-decile 전량 재편 가정은 실제 순환보다 turnover·비용을 과대 평가할 수 있음
  (반대로 실제 체결 슬리피지는 미반영 — net은 대체로 보수적).
- 주요 지표(10.79% TEST)는 **전체 EY 커버리지 유니버스** 기준. 이전 complement 실험의
  13.32%는 EY∩LOWMOM 축소 유니버스 기준 — 두 수치는 유니버스가 달라 직접 비교 금지.
- 종목 수가 적은 시점(2026 연중 7개월 등)의 연도별 숫자는 표본 수 차이로 해석 주의.
- survivorship(A1a 전용)·PIT는 기존 데이터 계약 그대로 — 완화하지 않음.

## 6. 재현

```
python research/strategy-lab/07_ey_independence_oos.py
```
출력: `reports/2026-09-06-ey-independence-oos/ey-independence-oos.json` (runtime 58.6s)
