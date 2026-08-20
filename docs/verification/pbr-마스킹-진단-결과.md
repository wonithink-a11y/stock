# pbr 제외 후 2차 효과(마스킹) 진단 — 결과

```
발행   2026-08-20 · Claude (직접 수행 — OpenCode/DeepSeek로 위임했던 DEEPSEEK-9가
       1시간 45분간 세션조차 생성하지 못하고 멈춰서(opencode.exe 프로세스는
       살아있었으나 opencode session list에 등록되지 않음) 사용자 지시로 중단하고
       직접 처리)
배경   docs/verification/DEEPSEEK-7-slot-marginal-표본확장-결과.md — pbr 하나가
       full 모델 IC를 지배한다(제거 시 IC 반토막). 다른 슬롯들의 marginal이 전부
       작은 게 "진짜 무효과"인지 "pbr에 가려서(masking) 안 보이는 것"인지 확인
```

## 방법 — 새 재실행 없이 기존 산출물 재활용

DEEPSEEK-7이 남긴 `%TEMP%\opencode\slot-marginal-400\snapshots_A.json`(400종목,
SEED=20260820, 51,200 스냅샷 · production `scoreStock()` 결과 포함)을 그대로
재사용했다 — PIT·A2a·A3·A4 재로딩 없이, 이미 계산된 `rows`(입력 원자료)만
가지고 새 config 조합을 채점했다. 재로딩 없이 순수 채점만 하니 51,200행 ×
16콤보 = 819,200회 `scoreStock()` 호출이 5.2초에 끝났다.

```
1  full_minus_pbr = full(17슬롯)에서 pbr만 뺀 stockData로 재채점
   → 검증: 기존 loo_pbr 점수와 완전히 일치(51,200행 전부 diff=0) — 재구성 로직 정확
2  나머지 16개 슬롯을 full_minus_pbr에서 하나씩 더 빼고(loo2_*) 재채점
3  ΔIC_new = IC(full_minus_pbr) − IC(loo2_slot) 를 원래 ΔIC_orig = IC(full) − IC(loo_slot)
   와 비교 — 커진 슬롯이 있으면 pbr이 가리고 있었다는 신호
```

production 코드(`lib/scoringEngine.js`·`lib/loadCriteria.js`) 읽기 전용, 저장소
무변경. 스크립트·산출물은 저장소 밖(`%TEMP%\claude\...\scratchpad\`)에만 있다.

## 결과 — marginOfSafety 하나만 뚜렷한 마스킹, 나머지는 없음

| slot | ΔIC d120 (pbr 있음) | ΔIC d120 (pbr 제외) | 차이 |
|---|---|---|---|
| **marginOfSafety** | +0.0001 | **+0.0116** | **+0.0115** ★ |
| perRelative | −0.0032 | −0.0001 | +0.0031 |
| peg | −0.0012 | −0.0004 | +0.0007 |
| roe | +0.0002 | +0.0006 | +0.0005 |
| macd | +0.0022 | +0.0024 | +0.0002 |
| shareholderReturn | +0.0052 | +0.0055 | +0.0003 |
| rsi | +0.0006 | +0.0007 | +0.0001 |
| (나머지 9개 슬롯) | — | — | \|차이\| ≤ 0.0008 |

나머지 9개(currentRatio·debtRatio·foreignNetBuy5d·institutionNetBuy5d·
movingAverageCross·operatingMarginTrend·revenueGrowthYoY·roeConsistency·
volumeConfirmation)는 차이가 0에 가깝거나 방향이 살짝 뒤집혀도 |Δ|≤0.0008로
표본오차 범위다.

## 메커니즘 — marginOfSafety는 pbr과 공식으로 얽혀 있다

`marginOfSafety = 1 − √(per×pbr/22.5)`(Graham 공식)이 pbr을 직접 포함한다.
실측 상관: **pbr vs marginOfSafety 순위상관 −0.8381**(n=18,257, p<0.001) — 매우
강한 음의 상관. pbr이 점수에 있으면 이 공유된 변동성을 pbr이 먼저 흡수해
marginOfSafety의 독립 기여가 거의 안 보이다가(+0.0001), pbr을 빼면 그 변동성의
일부를 marginOfSafety가 대신 잡는다(+0.0116) — **새 정보가 생긴 게 아니라
같은 신호를 다른 이름으로 다시 잡는 것**(DEEPSEEK-6의 sign축 해석과 같은
패턴 — 두 슬롯이 이미 강하게 얽혀있을 때 하나를 빼면 다른 하나가 그 자리를
메운다).

## 결론

**pbr의 압도적 지배력이 다른 슬롯의 신호를 광범위하게 가리고 있다는 증거는
없다.** 유일한 예외(marginOfSafety)도 "숨겨진 새 정보"가 아니라 pbr과의 공식적
중복(−0.84 상관) 때문이다. DEEPSEEK-7의 "pbr이 거의 유일하게 유효한 슬롯"이라는
결론은 이 진단으로도 흔들리지 않는다.

## 확인 / 추정 / 미확인

- **확인**: full_minus_pbr 재구성이 기존 loo_pbr과 완전 일치(재검증 성공) ·
  16개 슬롯 중 15개는 마스킹 없음 · marginOfSafety만 유의미한 차이(+0.0115) ·
  pbr-marginOfSafety 상관 −0.8381
- **추정**: marginOfSafety의 masking 메커니즘이 공식적 중복이라는 해석 — 직접
  분해(marginOfSafety를 per성분/pbr성분으로 나눠 각각의 marginal을 재는 것)는
  안 함
- **미확인**: peg·perRelative도 pbr과 약한 상관이 있을 수 있는데 이번엔 별도로
  안 쟀다(둘 다 마스킹 효과 자체가 작아 우선순위 낮음)
