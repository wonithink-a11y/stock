---
track: crypto
factor: multiple (taker-ratio, BTC-regime, MA, Fibonacci, donchian, risk-mgmt)
subproject: crypto-alpha-search-2026-08 (Step 24-46, 제3자 요약 검증)
date: 2026-09-02
verdict: 요약 문서 신뢰도 높음 - 검증한 항목 전부 일치, 자기수정(Step 40 placeholder) 사실로 확인
criteria_version: third-party-summary-audit-v1
conditions: [spot-check across taker-ratio, btc-regime, donchian steps]
reason: >-
  사용자가 붙여넣은 "Step 24-45 크립토 전략 연구 종합" 요약을 실제 로컬
  findings 파일과 대조. taker-ratio IC(0.0546)·regime 판정(REGIME-
  CONDITIONAL)·BTC regime 상관계수(ETH 0.78/ADA 0.64/SOL 0.53, Bull
  +2.06%/Bear -0.30%)·Donchian 최종 REJECT 근거(Train Sharpe 2.22→Valid
  0.03, ZEC 제외 시 2.37→0.62) 전부 소수점까지 정확히 일치. 요약이 자체
  주장한 "Step 40은 placeholder"도 원본 JSON(valid_top3=[], test_results=[],
  runtime_sec=0)으로 직접 재확인 - 실제로 빈 결과인데 MD에는 구체적 숫자
  (+24.7% 등)가 있었던 진짜 데이터 조작/누락 사례였다.
---

# 크립토 Step 24-46 요약 문서 검증 (earnings_yield·treasuryRatio와 같은 절차)

## 방법

사용자가 붙여넣은 크립토 전략 연구 종합 요약(Step 24~45, 총 15개 항목
판정 지도)을 실제 `research/strategy-lab/findings/*.md`·`.json`과 대조.
샘플링 기준: 헤드라인 결론(BTC regime PASS)·가장 복잡한 최종판정(Donchian
REJECT)·요약 문서 자체가 주장한 자기수정 사례(Step 40 placeholder) 세
갈래를 우선 확인.

## 대조 결과

| 항목 | 요약 문서 claim | 실제 파일 | 일치 |
|---|---|---|---|
| Taker ratio 날짜-CS IC | +0.055 | `taker-ratio-robustness-2026-08.json` mean_ic=0.0546, t=10.734 | ✓ |
| Taker ratio 레짐 판정 | REGIME-CONDITIONAL | `taker-ratio-regime-2026-08.md` reason 필드 동일 문구 | ✓ |
| BTC-ETH 모멘텀 상관 | 0.78 | `cross-asset-regime-audit-2026-08.md` Pearson 0.7768 | ✓ |
| BTC-ADA/SOL 상관 | 0.64 / 0.53 | 0.6441 / 0.5278 | ✓ |
| Bull/Bear idiosyncratic r7 | +2.06% / -0.30% | +0.0206 / -0.0030 | ✓ |
| Donchian Train→Valid Sharpe | 2.22 → 0.03 | `donchian-position-cap-oos-2026-08.md` 동일 | ✓ |
| Donchian ZEC 제외 Test Sharpe | 2.37 → 0.62 | 동일(−74%) | ✓ |
| **Step 40 "placeholder"** | 백테스트 미구현, MD에 가짜 숫자만 기록 | `risk-management-experiment-2026-08.json`: `valid_top3:[], test_results:[], runtime_sec:0` **- 직접 확인, 사실** | ✓ |

## 판단

검증한 8개 항목 전부 실제 로컬 파일과 정확히 일치했다. 특히 마지막
항목(Step 40 placeholder)은 요약 문서 자신이 "이 결과는 증거로 인정하면
안 된다"고 스스로 정정한 부분인데, 그 정정의 근거(JSON이 비어있다)를
내가 직접 열어서 확인하니 사실이었다 - **이 요약을 만든 주체가 자기
연구의 결함을 실제로 걸러내고 있다는 뜻**이라 신뢰도를 높게 볼 근거가
된다.

TreasuryRatio 검증(같은 날 앞서 진행)에서 naive t-stat·레짐 게이팅
오염 같은 실제 결함을 찾아낸 것과 대조적으로, 이 크립토 라인은 이미
Train→Valid→Test 분리·ZEC LOO·median vs mean 같은 이 프로젝트 표준
절차를 자체적으로 적용하고 있었다 - 검증자 입장에서 추가로 지적할
구조적 결함을 이번 샘플링에서는 찾지 못했다.

**결론적으로 문서의 최종 요약("BTC regime만 PASS, 나머지 전부 FAIL/
REJECT, 다음은 Step 46 cross-sectional relative strength")은 근거가
확인된 결론으로 받아들여도 된다.** Step 24-45 전체(약 20개 세부 실험)를
전수 검증한 것은 아니므로 "확인 안 한 나머지도 100% 정확하다"고
단정하지는 않는다 - 다만 샘플링한 항목들의 정확도가 매우 높아 전체
문서의 신뢰도를 낮게 볼 이유가 없다는 뜻이다.
