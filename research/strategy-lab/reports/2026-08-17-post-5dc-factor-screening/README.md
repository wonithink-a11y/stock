# 5DC 보류 후 신규 전략 탐색 — 종합 보고서 (2026-08-17)

5DC-v1A-P가 리스크 계약 결함(2×ATR[t] 스톱 타이밍, `docs/control/세션인수인계-2026-08-16.md` §6)으로
보류된 뒤, 대체 중장기 전략의 재료를 찾기 위해 두 트랙을 진행했다: ① 사용자가 과거 ChatGPT와의
대화를 정리해 둔 Book1~4 문서 세트 분석, ② 거기서 나온 Feature Gap 후보의 실제 팩터 유효성 검증.
**결론: 둘 다 "새 전략을 즉시 채택할 근거"는 못 찾았지만, 탐색해야 할 곳과 하지 말아야 할 것을
분명히 좁혔다.**

---

## 1. Book1~4 연구지도 — 원문 검증

`docs/Book1.zip~Book4.zip`(총 70개 파일, ChatGPT와의 대화를 정리한 시스템 설계 문서) 전체를
직접 읽어 검증했다.

- **완성된 매매법은 0건.** 구체적 진입/청산 조건, 검증된 threshold, 팩터 가중치, 실증된 주문
  규칙이 70개 파일 어디에도 없다. 전부 "어떻게 안전하게 구현할 것인가"를 다루는 아키텍처 문서다.
- **ChatGPT의 원래 가설(Book1=투자원리 / Book2=시스템구조)은 틀렸다.** 둘 다 사실상 같은
  15~20개 Engine 아키텍처를 다루고, Book2는 Book1의 확장/개정판에 가깝다.
- **Book3(20챕터, 구현·검증·운영)이 가장 직접적으로 연결된다.** 상당 부분이 현재 저장소의 실제
  구현 수치(A1a 2,579건, KR 가중치 등)와 정확히 일치 — 새 아이디어의 원천이 아니라 기존 구현의
  사후 문서화에 가깝다.
- **Book4(단기·초단기 확장)는 새 전략의 원천으로 보기 어렵다.** "백테스트 이익만 보고 전략으로
  채택하지 마라"는 절제 원칙이 본문 절반을 차지하고, 챕터가 두 벌(초안 중복) 존재하는 미완성
  문서다.

산출물: `book_research_map.md`(세션 임시 파일, 저장소에는 미커밋 — 필요시 재생성 가능,
`docs/Book1~4.zip`이 원본).

## 2. Feature Gap 분석 — Book3 Ch9 vs 현재 `KR-2.2.json`

| 축 | 현재 보유 | Book3 Ch9 후보 중 없는 것 |
|---|---|---|
| Fundamental | roe, roeConsistency, debtRatio, currentRatio, operatingMarginTrend, revenueGrowthYoY, shareholderReturn | Net Margin, ROA, Equity Growth, OCF, FCF |
| Valuation | perRelative(PER), pbr, peg, marginOfSafety | PSR, EV/EBITDA, Dividend Yield, FCF Yield |
| Technical | MA cross, RSI, MACD, volumeConfirmation, deadCatBounce | Momentum(raw), MA Distance, Volatility, ATR, Turnover, Drawdown |
| SupplyDemand | foreignNetBuy5d, institutionNetBuy5d, largeShareholderChange, buybackOrRetirement | Short Interest(의도적 배제), Credit Balance, Trading Value |

**가장 눈에 띈 것**: Momentum(추세 지속) 자체가 현재 시스템에 없었다 — 학술적으로 Value/Quality
만큼 검증된 팩터인데 빠져 있어 1차 실험 대상으로 선정.

## 3. Ch13(다중 시간축 Signal) 구조 확인

Book3 Ch13 원문 대조 결과, Momentum은 이 설계에서 이미 답이 정해져 있다:

- Momentum은 처음부터 "단기 Feature"로 분류(§13.9), Fundamental/Valuation(Strategic Score) 축이
  아니다.
- Strategic Score를 직접 수정하거나 Signal로 변환하는 건 명시적으로 금지(§13.46).
- 의도된 결합: `Strategic Score(Context/필터) + Momentum·Trend·Volume·Regime → Short-Term Signal`.
- 단, 이 Signal Layer 자체가 production에 없다(Book3 설계 문서일 뿐) — 실험은
  `research/strategy-lab`에서 진행해야 한다.

## 4. Strategy Lab 재사용성 평가 + 중요한 설계 발견

5DC-v1A-P의 `engine/{signals,execution,portfolio,data}` 계약(Signal/RiskSpec, Order/Fill,
CostModel, Portfolio 회계, Provider 3종)은 전략 로직과 완전히 분리돼 있어 새 전략에 그대로
재사용 가능하다 — 새 전략은 `strategies/<id>/{policy.json, rule.py}`만 구현하면 된다.

**단, 이 엔진은 "이산적 트레이드 신호" 전략(5DC 같은 BB/CCI 이벤트 트리거)을 위한 도구이지,
"매달 수백 종목이 동시에 조건을 만족하는 cross-sectional 필터"(Momentum>0 같은)를 검증하는
도구가 아니다.** `max_positions=10` 집중 슬롯 구조에 억지로 태우면 tie-break 규칙이 결과를
지배해 "팩터 자체가 유효한가"를 가리지 못한다(`benchmarks/b0_buy_hold.py`가 이미 같은 이유로
전체 엔진을 우회한 선례와 동일). → **Book3 Ch11이 제시하는 Decile/Forward-Return 분석**으로
전환, 엔진 미사용.

**추가로 확인된 데이터 공백**: "중장기 Score"의 과거 시계열이 존재하지 않는다.
`data/backfill/scores/`가 아예 없고, production `score()`는 "오늘" 시점만 계산한다. BF-1.1
(10년 소급 스코어 재현)은 원재료만 준비되고 미실행 상태(`CLAUDE.md` "언제든" 항목) — 원래
가설("Score 상위군 + Momentum")을 그대로 검증하려면 이 백필부터 별도로 실행해야 한다.

## 5. 실험 1 — Momentum12M Decile 분석

`research/strategy-lab/momentum_decile_analysis.py` (엔진 미사용, A2a 종가만 사용).
A1A_ONLY 2,578종목·월별 리밸런스 152개 시점·249,602 관측치.

| Decile | 20D | 60D | 120D |
|---|---|---|---|
| 1(모멘텀 최저) | 1.67% | 3.19% | **4.40%** |
| 10(모멘텀 최고) | 0.18% | 0.72% | **1.98%** |

Spearman 상관(decile 순위 vs 수익률): 20D -0.31, 60D -0.56, **120D -0.88**. `momentum>0` 그룹이
`momentum≤0` 그룹보다 이후 수익률이 낮다(3.49% vs 4.11%, 120D).

**재검증(12-1 모멘텀, 최근 1개월 제외 — Jegadeesh-Titman 표준)**: 방향 동일 유지
(Spearman 120D -0.53, decile10 2.38% vs decile1 3.78%) — 방법론(최근월 오염) 문제가 아니라
진짜 역전 패턴으로 확인.

**결론: 이 데이터에서 "Momentum12M>0 필터" 가설은 기각. 오히려 저모멘텀 종목군이 일관되게
좋았다(역발상/평균회귀 신호 — 별도 가설로 이어갈 수는 있으나 이번 라운드에서는 미착수).**

산출물: `2026-08-17-momentum-decile-analysis/{v1.json, v2_skip1m_recheck.json}`

## 6. 실험 2 — Net Margin Decile 분석

`research/strategy-lab/net_margin_decile_analysis.py`. FCF Yield·EV/EBITDA·ROA는 원천 데이터
자체가 없고(OCF·CapEx·EBITDA·총자산 미수집), PSR·PBR은 peg/perRelative를 이미 막고 있는
A2a(수정주가)-A3c(비조정 발행주식수) 조정 불일치를 재현하므로 제외 — Net Margin(=netIncome/
revenue)만 새 블로커 없이 즉시 검증 가능해 선정. A3 재무데이터 PIT as-of 조인(availableFrom ≤
리밸런스일), 2,516종목·152개월·223,799 관측치.

| Decile | 20D | 60D | 120D |
|---|---|---|---|
| 1(최저) | 0.86% | 2.16% | 3.52% |
| 6(중간, 최고치) | 0.89% | 2.45% | **4.50%** |
| 10(최고) | 0.70% | 1.66% | 2.82% |

Spearman: 20D -0.14, 60D -0.05, 120D **+0.03**(사실상 0). Decile 순서와 수익률 사이에 추세가
없다. 흑자/적자 이진 분할도 3.57% vs 3.04%로 방향은 있으나 decile 패턴이 뒷받침하지 않아 우연
범위로 판단.

**결론: Net Margin 단독으로는 예측력 확인 안 됨(무신호, 역방향도 정방향도 아님).**

산출물: `2026-08-17-net-margin-decile-analysis/v1.json`

## 7. 종합 결론

```
Book1~4                새 전략 원천 아님 — 시스템 설계 문서일 뿐(1번에서 확정)
Feature Gap 8개 후보    2개 검증 완료(Momentum 역전·Net Margin 무신호),
                       4개는 원천 데이터 없음(FCF/EBITDA/ROA) 또는 조정 불일치 재현(PSR/PBR),
                       나머지(Volatility·Drawdown·ATR·Turnover·MA Distance·Trading Value 등) 미검증
Score 히스토리          존재하지 않음(BF-1.1 미실행) — "Score+Momentum" 원안은 이 백필 없이는
                       검증 불가
Strategy Lab 엔진       5DC 계약(signal/execution/portfolio)은 재사용 가능하지만
                       cross-sectional 팩터 검증에는 안 맞는 도구 — Decile 분석으로 대체
```

**단일 팩터 스크리닝 2연속 무위(역전 1건, 무신호 1건)** — 남은 후보를 계속 하나씩 찍어보기 전에
사용자가 방향을 다시 정할 시점. 검토했던 선택지:

1. 남은 후보(Volatility·Drawdown 등 기술적 팩터) 계속 개별 검증
2. **(이번에 실행)** 여기서 멈추고 결과 종합 — 본 문서
3. 단일 팩터 대신 조합(예: 저모멘텀 + 흑자기업, 실험 1의 역발상 신호 포함) 검증으로 전환
4. Score 히스토리 백필(BF-1.1 축소판)을 먼저 실행해 원래 가설(Score+Momentum)로 돌아가기

## 8. 코드/데이터 변경 이력 (이번 라운드)

프로덕션 코드·정책 무변경. 신규 파일:

```
research/strategy-lab/momentum_decile_analysis.py       (신규, 엔진 미사용 팩터 검증 스크립트)
research/strategy-lab/net_margin_decile_analysis.py      (신규, momentum_decile_analysis 재사용)
research/strategy-lab/reports/2026-08-17-momentum-decile-analysis/{v1.json,v2_skip1m_recheck.json}
research/strategy-lab/reports/2026-08-17-net-margin-decile-analysis/v1.json
research/strategy-lab/reports/2026-08-17-post-5dc-factor-screening/README.md  (본 문서)
```

전부 `data/backfill/`을 읽기 전용으로만 사용(규칙 4 준수), 아직 git add/commit 안 함 —
커밋 여부는 사용자 확인 후.
