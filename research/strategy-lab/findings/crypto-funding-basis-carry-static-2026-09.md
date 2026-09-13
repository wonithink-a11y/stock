---
track: crypto
factor: funding-basis-carry-static
date: 2026-09
verdict: REJECT
original_verdict: "A — 유력 후보 승급 (Stage 2-5, OpenCode 자체판정, Claude 독립검증에서 기각됨)"
criteria_version: stage2-5
conditions: ["직전(Stage 2-4) 재현", "Sharpe 5.69 수식 검증", "delta-neutral 구조 타당", "비용 stress(0~20bp) 유지", "funding haircut 50%에서 유의미한 양의 CAGR", "특정 연도 의존 심하지 않음"]
reason: "F2_static_short+spot(short 1x perp + long 1x spot, 재밸런싱 없음) 검증. CAGR 12.50%·Sharpe 5.692·MDD −1.58%·final 2.197(2019-12-23~2026-08-29, 6.68yr)로 Stage 2-4 재현 정확. Sharpe=mean/std×√8766(수식 직접 재검증, hourly r mean 1.35e-05·std 2.21e-04, 8h 그리드 Sharpe 11.60). 수익의 100%가 funding(L_fund +0.786 vs price +0.001)이라 delta-neutral 정당. 20bp/side까지 CAGR 불변(1회성 4side). haircut 50%에서도 CAGR 6.08%. 연도별 전부 양수(2019 −0.00/2020 +18.7/2021 +36.2/2022 +4.2/2023 +8.0/2024 +12.7/2025 +5.3/2026 +1.7%). 자본구조: spot 전액 + perp margin 1~5% → ROIC 11.7~12.3%로 경미한 회석. [Claude 독립검증, 2026-09-13] 이 자본구조는 생존 불가능 — isolated 마진 1~2.5%로는 실제 BTC 가격 데이터(2019-12-23 진입 가정)에서 14일 만에 +2%, 16일 만에 +10% 상승해 유지증거금(0.4~0.5%)을 즉시 소진, 청산된다. 백테스트는 포트폴리오 델타중립 P&L만 계산했고 개별 레그(perp)의 증거금 유지 제약을 전혀 반영하지 않았다 — 스팟 매도차익이 같은 지갑에서 자동 상계되는 구조(Binance Portfolio Margin 등 적격 계정 전용, 자체 헤어컷 있음)가 아닌 한 이 트레이드는 6.68년은커녕 첫 3주도 못 버틴다. 판정 A→REJECT."
cagr: 12.5
sharpe: 5.692
mdd: -1.58
win_rate: null
n: 4
t_stat: null
---

# BTC Funding 기반 Delta-Neutral Carry — F2_static_short+spot 검증 (Stage 2-5, 2026-09)

> 검증 관측치. **최종 판정: A — 유력 후보 승급.**
> Stage 2-4(후보 스크리닝, verdict B)에서 "다음 실험"으로 지정된 단일 전략을
> READ-ONLY로 독립 재검증했다. 산출 스크립트(임시, 커밋 대상 아님):
> `%TEMP%/opencode/stage2_5_f2static.py`, `stage2_5_supp.py`.

## 0. 전략 정의 (Stage 2-4와 동일)

| 항목 | 값 |
|---|---|
| 표적 | **F2_static_short+spot** |
| 구성 | perp **short 1x**(side=−1, 고정) + spot **long 1x**(index 프로xy), 재밸런싱 없음 |
| price PnL | `−mark_ret + index_ret` (×equity 전개, 1x notional) |
| funding | `−side×r = +r` (short가 r>0 수취), 8h 그리드 이벤트에서 신용 |
| 거래 | 진입/청산만 → **4 side** (spot in/out + perp in/out) |
| leverage | 두 leg 각 1x notional, net delta ≈ 0 |
| 가격 데이터 | `basis/1h/BTCUSDT_1h.parquet` mark_close·index_close (58,574 bar) |
| funding 데이터 | `funding/BTCUSDT.parquet` 8h (`index.floor('h')`로 jitter 정규화), 7,320 이벤트 |

## 1. 재현 — Stage 2-4와 정확 일치

| 지표 | Stage 2-5 독립 재계산 | Stage 2-4 |
|---|---|---|
| period | 2019-12-23 11:00 ~ 2026-08-29 00:00 (6.68 yr) | 동일 |
| **CAGR** | **12.50%** | 12.50% |
| **Sharpe** | **5.692** | 5.69 |
| **MDD** | **−1.58%** | −1.58% |
| **final equity** | 2.1974 (base_7bp 2.1913) | 2.20 |
| **funding PnL(log)** | +0.7859 | +0.79 |
| **price PnL(log)** | +0.0012 | +0.001 |
| cost PnL(log) | −0.0028 | −0.003 |
| 거래 횟수 | 4 | 4 |

### Sharpe 5.69 수식 검증
```
Sharpe = mean(hourly_ret) / std(hourly_ret) × √8766
       = 1.3471e-05 / 2.2145e-04 × 93.62 = 5.692
```
구현 오류 없음(수식·값 직접 재계산 일치). hourly σ = 0.0221%/h.
★ 단, funding이 8h마다 lumpy로 도착해 시간 단위 연율화가 Sharpe를 과대평가하는
구조라는 한계가 있다 — 자연 결제 주기인 **8h 그리드 연율 Sharpe = 11.60**
(n=7,321) 국가 그리드를 바꿔도 위험조정 성과 유지.

## 2. 비용 Stress (0/1/3/5/7/10/20 bp per side)

| bp/side | CAGR | Final | Sharpe | MDD |
|---|---|---|---|---|
| 0 | 12.50% | 2.1974 | 5.69 | −1.58% |
| 1 | 12.50% | 2.1965 | 5.69 | −1.58% |
| 3 | 12.50% | 2.1948 | 5.69 | −1.58% |
| 5 | 12.50% | 2.1930 | 5.69 | −1.58% |
| 7 | 12.50% | 2.1913 | 5.69 | −1.58% |
| 10 | 12.50% | 2.1886 | 5.69 | −1.58% |
| 20 | 12.50% | 2.1799 | 5.69 | −1.58% |

비용이 진입·청산 1회성(총 4 side)뿐이고 재밸런싱이 없어(무지속 회전) 최대 20bp/side
(=총 80bp 1회)에서도 CAGR 불변. **비용에 극도로 둔감**.

## 3. Funding Haircut (0 cost)

| haircut | CAGR | Final |
|---|---|---|
| 100% | 12.50% | 2.1974 |
| 90% | 11.19% | 2.0313 |
| 75% | 9.24% | 1.8054 |
| **50%** | **6.08%** | **1.4833** |
| 25% | 3.00% | 1.2186 |
| 0% | 0.02% | 1.0012 |

따라서 잔여 수익(0% haircut remnant CAGR 0.02%)은 사실상 0 →
**수익의 100%가 funding에서 발생**, delta-neutral 구조 정당. 50% haircut에서도
CAGR +6.1%로 유의미한 양수.

## 4. 실제 자본 구조 (1 BTC spot long + 1 BTC perp short, ref BTC ≈ $77,737)

- **spot 매수 자금**: BTC 1개 전액 즉시 결제 ≈ **$77,737** → 선순위 고정자본.
- **perp margin (isolated USDT-M)**: initial margin ≈ 1~2.5% → $777~$1,943,
  maintenance ≈ 0.4~0.5% → $311~$389.
- **liquidation buffer**: 표본 내 premium(마크−index) 실측 ±0.3% 범위지만,
  funding 결제 사이(8h) 미결 offset이 isolated에선 반영 안 되므로 마진+버퍼를
  notional의 **3~5%($2,300~$3,900)** 권장.
- **notional 일치**: 두 leg 1 BTC로 항상 매칭(delta≈0, USD 값은 변해도 notional은 1:1).
- **"1x"의 의미** (Stage 2-4): perp leg notional = equity 1배(`≤1x` 준수),
  net market exposure ≈ 0. 총 자본은 perp margin이 아니라 **spot leg 전액이 지배**.
- **12.5% CAGR의 자본수익률 해석가능성**: YES, 거의 1:1. 해당 수익률은 notional 기준
  funding-yield이고 실제 투입자본 ≈ spot notional이라 보정이 미미하다.
  margin+버퍼를 합산하면 ROIC = 12.31%(m1.0%) / 12.07%(m2.5%) / 11.66%(m5.0%)/
  10.89%(m10%) → **실현 ROIC ≈ 11.7~12.3%**. 재투자 복리 가정, margin 기회비용 포함이면
  소폭 lower.

## 5. 최종 판정 — **A (유력 후보 승급)**

| A 조건 | 판정 |
|---|---|
| Stage 2-4 재현 | ✅ 전 지표 일치 |
| Sharpe 5.69 수식 검증 | ✅ (8h 그리드 11.60에서도 유지) |
| delta-neutral 타당 | ✅ price PnL 0.0012(≈0.1%), funding 100% |
| 비용 stress 유지 | ✅ 20bp/side까지 CAGR 불변 |
| haircut 50% 의미 있는 CAGR | ✅ +6.08% |
| 연도 의존 | ✅ 7개 년도 전부 양수, 단 2021(+36.2%)이 총기여 ~36% |

**단서 (승급 시 수반)**: ① 2021 funding 집중(불장) 존재하나 전 연도 양수·
haircut 버팅로 "심한" 의존은 아님. ② hourly Sharpe는 lumpy 구조상 과대평가
소지 — 8h 그리드 수치가 정직. ③ 실전 변환 시 마진 회석(ROIC ≈ 11.7~12.3%)과
isolated perp 단독 청산 리스크를 감안 필요. ④ spot leg은 index가 아니라 실제
Binance SPOT으로 실행해야 함(추적 차이 소폭 발생).

## 6. Claude 독립검증 — 마진/청산 생존성 (2026-09-13, 판정 A→REJECT)

Stage 2-5는 ③에서 "isolated perp 단독 청산 리스크를 감안 필요"라고만 적고 정량화하지
않았다. `data/crypto/basis/1h/BTCUSDT_1h.parquet`(mark_close, 실측)로 직접 계산했다.

```
진입 가정 시점: 2019-12-23 11:00 UTC, mark 7,554.17
+2%  상승 도달: 2020-01-06 22:00 UTC  (14일 후)
+5%  상승 도달: 2020-01-07 17:00 UTC  (15일 후)
+10% 상승 도달: 2020-01-08 00:00 UTC  (16일 후)
```

perp short 레그의 PnL은 대략 `-(notional) × (mark/entry - 1)`이다. 본문 §4가 제시한
initial margin 1~2.5%·maintenance 0.4~0.5%로는 가격이 진입가 대비 **약 2%만 올라도**
(유지증거금까지 남은 완충폭 ≈ initial−maintenance ≈ 1.6~2.1%p) 청산 트리거에 도달한다.
실측상 그 2% 상승은 **진입 14일 후**에 이미 일어났다 — "4 side, 6.68년 무재조정 보유"
가정 자체가 첫 3주를 못 넘긴다. 완충을 본문의 "권고" 3~5%로 넉넉히 잡아도 10% 상승
(16일 후 도달)이면 소진되고, 이후 이 데이터 구간엔 BTC가 7,554→126,010까지 오르는
+1,568% 구간이 포함돼 있어(§0 max rise) 어떤 상식적 정적 마진 비율도 무재조정으로는
버티지 못한다.

**결정적 결함**: 이 백테스트는 "스팟 롱 + 퍼프 숏의 포트폴리오 델타중립 P&L"만 계산했다.
실제 거래소에서 스팟 지갑의 미실현이익이 퍼프 지갑의 증거금 부족을 자동으로 메워주지
않는다 — 그런 상계가 되려면 Binance Portfolio Margin 같은 **적격 계정 전용 교차담보
모드**(자체 담보인정비율 헤어컷 있음, 리테일 기본 아님)가 필요하고, 이 검증은 그 모드를
가정하지 않았다(§4는 "isolated USDT-M"로 명시). 즉 보고된 CAGR 12.5%·Sharpe 5.69는
**생존 불가능한 계좌 구조에서 나온 사후적 P&L**이며, 실제로는 이 기간 내내 여러 차례
청산·재진입(과 그때마다의 손실 실현·슬리피지)이 필요했을 것이고 그 비용은 backtest에
전혀 반영되지 않았다.

## 7. Claude 독립검증 ② — 재도전 옵션 ①(거의 전액담보) 실측 (2026-09-13)

§6 마지막에 제안한 "① 거의 전액 담보로 ROIC 재계산"을 실제로 돌려봤다. 같은
`mark_close`(hourly, 실측) + `fundingRate`(실측) 원자료로 두 가지 자본화 방식을
시뮬레이션했다(스크립트는 임시, 커밋 대상 아님 — 재현 원자료·로직은 본 절에 전부 기록).

**(a) 능동 재조정 방식** — 마진비율 5% 밑으로 가면 15%로 top-up, 40% 넘으면 회수:

```
top-up 발생 99회 (그중 강제청산 후 재진입 1회, 매 시간 단위 점검 한계)
마진지갑에 실제 필요했던 최대 순자본(peak): $91,425 = 진입 notional($7,554)의 1,210%
총 필요자본(스팟+마진 peak) = $98,979   (vs 본문 §4가 가정한 ~$7,743)
실현 CAGR (실제 필요자본 기준) = -1.20%/yr
```

**(b) 완전 무재조정(§6에서 제안한 "① 거의 전액담보") 방식** — 진입 시 한 번만 충분한
초기증거금을 넣고 6.68년간 절대 추가 입출금 없이 버틴다고 가정, 청산 0회를 보장하는
최소 초기증거금을 역산:

```
필요한 정적 초기증거금 = $85,184 = 진입 notional의 1,128%
  (필요 시점: 2025-10-06, BTC $125,989 — 이 구간의 최고가, 진입가 대비 +1,568%)
기간 내 누적 손익(가격PnL+funding, $) = -$34,069  (순손실 — funding 수취가 가격 역행분을
  다 못 메움)
총자본(스팟+정적버퍼) = $92,738
실현 CAGR (총자본 기준) = -6.62%/yr
```

**결론**: ①(거의 전액담보) 방식은 자본효율만 낮추는 게 아니라 **이 정확한 6.68년
구간에서 수익 자체를 마이너스로 뒤집는다.** 이유는 단순하다 — 이 표본기간은 BTC가
진입가 대비 최대 +1,568%(최종 +928%)까지 오른 강세장이고, funding 총수취(연 log
+0.786, 대략 6.68년에 걸쳐 notional의 ~80~90% 상당)로는 그만한 가격 역행 손실을
못 이긴다. ②(능동 재조정)도 결과는 마찬가지다(-1.2%/yr) — top-up 정책(5%/15%/40%
트리거)을 바꿔도 필요자본의 자릿수(notional의 수백~1천%대)는 BTC가 그 기간 몇 배로
뛰었다는 사실 자체에서 나오므로 바뀌지 않는다.

**최종 권고: STOP, 재도전 조건 없음.** Stage 2-5·§6이 제안했던 두 재도전 경로(①
전액담보, ②능동 재조정) 중 ①은 이번에 직접 검증해 마이너스로 확인됐고, ②도 동일 자본
스케일이라 결과가 다르지 않을 것으로 판단한다(추가 검증 불필요 — 자본 요구량이 이미
notional의 10배 이상이라는 게 핵심이지 재조정 정책의 세부는 부차적이다). 남은 유일한
경로는 Binance Portfolio Margin(스팟을 퍼프 담보로 인정하는 교차담보) 활용인데, 이는
①②와 달리 이 저장소 데이터만으로 검증 불가(그 모드의 실제 담보인정비율·헤어컷은
계정별·시점별 정책이라 별도 실측 필요)이고, 이 프로젝트는 "조회·알림 전용"이라 크립토
실주문 인프라 자체가 없다 — 그 인프라를 새로 만드는 건 이 판정과 무관한 별도의 큰
스코프 결정이라 사용자 GO 없이는 열지 않는다.

## 다음 결정 사항 (사용자 GO/STOP)

- 위 REJECT 판정(재도전 경로 소진 포함)에 동의하는지
- Binance Portfolio Margin 경로를 새 스코프로 열지(신규 인프라 결정, 이 판정과 별개)
- findings 등록 완료(registry `build_findings_registry.py` 재생성, verdict=REJECT 반영됨, 2026-09-13)