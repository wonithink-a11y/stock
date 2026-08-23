# Overnight macro-regime 교차후보 종합 (2026-08-24)

2026-08-24 새벽 OpenCode(opencode/x-preview-f-free) 병렬 3job + Claude 직접
진단 1건의 종합. 6개 연구 후보(PBR·CAND1·Opening Fade·LOWMOM60+기관수급·
TREND-BREAKOUT-v1·5DC-v1A-P) × macro axis 최대 10개 조합을 전부 채웠다 —
"이미 검증된 전략 × 아직 안 써본 축" 소진, 이 방향의 기계적 확장은 여기서
멈춘다.

## 실행 내역

| Job | 대상 | 결과 |
|---|---|---|
| job1 | LOWMOM60+기관수급, 10축 전체 | findings/lowmom60-macro-regime-check-2026-08.md |
| job2 | PBR·CAND1·OpeningFade, 미검증 6축 | findings/{pbr,cand1,opening-fade}-macro-extra-axes-2026-08.md |
| job3 | TREND-BREAKOUT-v1·5DC-v1A-P, 10축 전체 | findings/{trend-breakout,5dc-v1a-p}-macro-regime-check-2026-08.md |
| 부수 | `pbr_vs_ew_monthly_mtm.py` exit 중복버그 발견·수정 | findings/pbr-vs-ew-monthly-mtm-exit-dedup-fix-2026-08.md (PBR 결과 무영향 확인) |

## 교차후보 패턴 — 두 개의 서로 다른 클러스터

**① 미국10Y + 한국 신용스프레드(금리인상 클러스터)** — PBR·LOWMOM60·
TREND-BREAKOUT-v1·5DC-v1A-P **4개 후보**에서 반복 등장, 전부 2022년
제외해도 방향 유지:

| 후보 | 미국10Y hiking 방향 | 신용스프레드 확대 방향 |
|---|---|---|
| PBR | 초과수익 **+** (원 조사) | 초과수익 **+** |
| LOWMOM60 | 절대수익 **+**(기여율 74.7%) | 절대수익 **+**(기여율 80.4%) |
| TREND-BREAKOUT-v1 | 절대수익 **-**(기여율 76.6%) | 절대수익 **-**(기여율 87.8%) |
| 5DC-v1A-P | 절대수익 **-**(기여율 87.8%) | 절대수익 **-**(회사채AA-3년 포함 시 105~117%) |

방향은 전략 성격을 그대로 반영한다 — PBR·LOWMOM60(가치·역모멘텀류)은
금리인상기에 **강하고**, TREND-BREAKOUT·5DC(추세추종류)는 금리인상기에
**약하다**. 같은 축이 정반대로 갈라지는 게 우연이 아니라 두 전략군의
경제적 성격 차이로 일관되게 설명된다 — 이 축의 신뢰도를 오히려 높이는
증거.

**② 한국 일반순환지수(경기동행)** — PBR·CAND1·Opening Fade **3개 후보**
에서 유의미(job2 발견), LOWMOM60·TREND-BREAKOUT·5DC에서는 약하거나
연도별로 불안정. CAND1과 Opening Fade는 부호까지 반대라 "이 축이 좋다"가
아니라 "전략별 조건부"로만 해석 가능.

**KOSPI(한국 증시 자체)** — LOWMOM60·TREND-BREAKOUT-v1·5DC-v1A-P
**3개 후보 전부에서 일관되게 역방향**(KOSPI 상승기에 오히려 부진) — 세
전략 다 "시장 자체 방향에 역행하거나 무관하게 작동해야 하는" 성격(역모멘텀·
추세추종의 손절 국면)과 맞아떨어진다. PBR·CAND1·Opening Fade에서는 이
축이 두드러지지 않았다.

## 해석상 주의

- 전부 **월별/거래별 집계 기준의 상관관계 관찰**이다 — 인과관계 확정도,
  진입 타이밍 필터로서의 경제적 가치 검증도 아니다. PBR에서 이미
  증명됐듯(`pbr-ratefilter-backtest-2026-08.md`·`pbr-exposure-overlay-
  vs-ranking-cut-2026-08.md`) **"상관관계가 있다"와 "필터로 쓰면
  이득이다"는 다른 질문**이다 — 나머지 5개 후보에 대해 이 필터화 backtest는
  아직 아무것도 안 했다.
- CAND1·Opening Fade는 데이터 창이 ~1년뿐이라 연도별 검증(ex-2022 등)이
  원리적으로 불가능 — 참고 수준으로만 취급한다.
- PBR/CAND1/OpeningFade는 6개 추가축만 검증해 `krCorpAA3y`(원본 회사채
  금리 레벨) 자체는 안 봤다(파생인 `krCreditSpreadBp`만 검증) — LOWMOM60·
  TREND-BREAKOUT·5DC는 10축 전부 검증. 사소한 공백이라 별도 job으로
  안 채웠다.

## 다음으로 열리는 질문 (결정 안 함, 기록만)

1. TREND-BREAKOUT-v1·5DC-v1A-P·LOWMOM60에도 PBR처럼 "타이밍 필터로
   실제 backtest"를 해볼 가치가 있는가 — PBR에서는 이 필터화가 결국
   기각됐다(구성효과와 섞여 순수 타이밍 가치 없음, 08-24 세션). 같은
   함정에 빠질 가능성이 높아 **새로 하기 전에 이 결과부터 참고하라는
   경고**로 남긴다.
2. `v3_bollinger_rsi`·`v6_acc_price` 등 예전 탐색 후보들도 이 macro
   regime 패턴에 넣을 수 있는지는 **상태 확인이 먼저 필요**(이미 결론난
   죽은 후보일 수 있음) — 기계적으로 바로 확장하지 않았다.
