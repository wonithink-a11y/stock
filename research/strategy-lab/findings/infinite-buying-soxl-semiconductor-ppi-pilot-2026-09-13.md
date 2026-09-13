---
track: kr
factor: infinite-buying-soxl-semiconductor-ppi-pilot
date: 2026-09-13
verdict: REJECT
original_verdict: null
criteria_version: null
conditions: ["FRED WPU1178·PCU3344133441 두 계열 모두 수집(둘 다 무료, macro_common.fred() 기존 헬퍼 재사용, 신규 외부소스 없음), SOXL 상장 이후(2010~) n=198만 유효", "availableFrom = 월말+20일(미 BLS PPI 발표관례 보수적 가정)", "4 factor(YoY·3M·6M 변화·YoY가속) x 3 horizon(1/3/6개월), soxl_leadlag_common 공용 배터리(Spearman+HAC+비중첩+분위수+전환이벤트)", "threshold 최적화 없음"]
reason: "DART(기업 매출)·TSMC(파운드리 매출) 두 REJECT와 명시적으로 다른 축(가격, PPI)으로 SOXL 선행수익률 예측 가능성을 시험했다. WPU1178·PCU3344133441 두 계열 모두 동일 배터리를 돌렸다(후자가 실제로 FRED 블로그가 인용한 산업기준 계열 - §1 정정 참고). 두 계열 결과가 실질적으로 같다: naive Spearman 전부 무의미(|rho|<=0.075, p>=0.29), HAC에서 ppi_yoy_accel/1개월만 유의(WPU1178 p=0.001, PCU3344133441 p=0.012)하나 같은 factor의 3/6개월은 두 계열 다 무의미하고 비중첩·분위수·전환이벤트 어디서도 뒷받침이 없어 다중검정 잡음으로 판단(TSMC의 6개월 비중첩 단독 히트와 같은 패턴 - 두 계열이 고도로 상관돼 있어 반복 검출도 독립 확증이 아니다). 분위수 forward return은 단조성 없음. YoY 상승전환·하락전환 이벤트가 두 계열 모두 방향 무관 거의 동일한 수익률(TSMC와 동일한 반증 패턴). DART·TSMC·PPI(2계열) 전부 REJECT로 수렴 - 판정 REJECT."
cagr: null
sharpe: null
mdd: null
win_rate: null
n: 198
t_stat: null
---

# SOXL 산업사이클 연구 — 반도체 PPI(가격) 파일럿 (2026-09-13)

> `soxl-semiconductor-industry-fundamentals-line-closure-2026-09-13.md`가
> 닫은 것은 "매출·판매 성장률" 축이었고, 그 문서 §6이 예고한 대로 **가격
> (price)**은 별도의 새 가설이라 여기서 독립적으로 시험한다.

## 1. 데이터 — 이번엔 스크레이핑 문제 없음

FRED `WPU1178`("Producer Price Index by Commodity: Machinery and Equipment:
Semiconductors and Related Solid-State Devices") — 1965~2026, 729개월,
`macro_common.fred()`로 그냥 조회됨. TSMC 때와 달리 Cloudflare 차단도,
SEMI 때처럼 무료 배포 중단도 없다 — 신규 외부소스 통합도 아니다(이미 이
저장소가 쓰는 FRED 헬퍼 재사용). SOXL 상장(2010)이 병목이라 실제 검증
가능 구간은 n=198개월.

**정정(2026-09-13, 커밋 전 독립검토에서 발견)**: 최초 작성 시 "WPU1178이
FRED 블로그가 인용하는 표준 계열"이라 적었는데 틀렸다. 블로그(AI
investment and semiconductor prices, 2026-06-29) 원문을 직접 열어 대조한
결과 실제로 인용된 건 **산업기준 PPI `PCU3344133441`**다 — 블로그 수치
(2026-01 61.6 → 04 73.1)가 WPU1178(같은 시점 72.8)이 아니라 PCU3344133441
(같은 시점 61.583 → 73.184)과 정확히 일치한다. 원래 "방향·크기 일치
확인"이라던 검산은 %변화율(둘 다 +19%대)만 보고 절대수준(72.8 vs 61.6)
차이를 놓친 오류였다. 그래서 **두 계열 모두 같은 배터리로 재검증**했다 —
아래 §2는 두 결과를 병기한다.

## 2. 결과 — 두 계열 모두 DART·TSMC와 같은 반증 패턴

| | WPU1178(상품기준, 최초 검증) | PCU3344133441(산업기준, 블로그 인용 계열, 재검증) |
|---|---|---|
| naive Spearman 12개 조합 | 전부 무의미(\|rho\|≤0.065, p≥0.36) | 전부 무의미(\|rho\|≤0.075, p≥0.29) |
| HAC 유의 조합 | ppi_yoy_accel/1m만 p=0.001 | ppi_yoy_accel/1m만 p=0.012 |
| 같은 factor 3m/6m(HAC) | p=0.193 / 0.930 | p=0.200 / 0.760 |
| 분위수 단조성 | 없음 | 없음 |
| 상승전환 fwd6m | +46.9%(n=7) | +50.5%(n=6) |
| 하락전환 fwd6m | +50.1%(n=8) | +66.7%(n=5, 오히려 더 높음) |

**두 계열이 사실상 같은 결과를 낸다** — 놀랍지 않다, WPU1178과
PCU3344133441은 같은 산업의 서로 다른 분류기준일 뿐 고도로 상관돼 있어
"두 계열에서 재현"이 독립 확증이 되진 않는다. HAC에서 매번 같은 factor·
horizon(`ppi_yoy_accel`/1개월)만 걸리는 것도 오히려 다중검정 잡음이라는
판단을 강화한다 — 같은 잡음의 원천(같은 근본 시계열)에서 나온 우연이라는
뜻이다. 다른 factor의 3/6개월은 두 계열 다 무의미하고, 비중첩·분위수·
전환이벤트 어디서도 뒷받침이 없다 — TSMC의 "6개월 비중첩 단독 히트"와
같은 모양이라 신호로 채택하지 않는다.

**분위수**: 두 계열 다 단조 관계 없음(Q1만 유독 낮고 나머지는 뒤섞임).

**상승전환·하락전환**: 두 계열 다 **방향과 무관하게 거의 같은(오히려
PCU3344133441은 하락전환이 더 높은) 수익률.** TSMC에서 봤던 것과 동일한
반증 — 이 이벤트 자체가 차별적 정보를 안 준다.

## 3. 판정 — REJECT

DART(기업 매출)·TSMC(산업 매출)·PPI(가격, 2계열 교차검증) — **서로 다른
변수 유형이 전부 REJECT로 수렴했다.** `soxl-semiconductor-industry
-fundamentals-line-closure`가 이미 "매출/판매" 축에 한정해 스코프를
좁혀뒀는데, 이번 결과로 그 문서가 아직 열어뒀던 유일한 후보(가격)까지
닫혔다 — 이번엔 최초 검증에서 놓쳤던 "실제로 관련성 높은 계열"까지
확인했으므로 이 결론에 남은 미검증 구멍은 없다.

## 4. 이 REJECT의 정확한 범위

이전 문서와 같은 원칙 — "반도체 가격 사이클이 존재하지 않는다"가 아니라
**"공개적으로 무료 확보 가능한 반도체 가격 지표(PPI)로는 SOXL 선행수익률
예측 신호를 찾지 못했다"**다. 시험 안 한 것: DRAM/NAND 스팟·계약가(대부분
유료), WSTS ASP(무료 확인됨, 미시도), CapEx 가이던스·주문잔고(ASML
bookings 등, 다른 메커니즘 — 실적/가격이 아니라 선행 주문).

## 5. 산출물

- `research/strategy-lab/soxl_leadlag_common.py` — 이번에 추출한 공용 검증
  배터리(Spearman+HAC+비중첩+분위수+전환이벤트), selftest 2/2
- `research/strategy-lab/semiconductor_cycle_ppi.py --series {WPU1178,PCU3344133441}` — selftest 5/5
- `research/strategy-lab/data/semiconductor-cycle/semiconductor_ppi_monthly_{series}.parquet` — 계열별 저장
