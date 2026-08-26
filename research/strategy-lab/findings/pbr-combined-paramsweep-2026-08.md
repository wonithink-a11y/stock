# PBR dropout×MAX제외 파라미터 스윕 — 시너지는 재현, 최적점은 이동 (2026-08-26)

세션인수인계-2026-08-26.md §5-4(파라미터 스윕, 민감도 확인)와, 결합 실험
(findings/pbr-dropout-maxexcl-combined-2026-08.md)이 nDrop=3·percentile=80%
단일 조합에서만 나온 초가산적 효과인지 확인하는 후속. `run_pbr_combined_
paramsweep.py`(커밋) — nDrop∈{2,3,5} × exclusionPercentile∈{0.7,0.8,0.9}
9격자를, bars·valuation을 한 번만 로드해 engine의 `run_smoke(rule_module=...)`
로 디스크에 selection.json을 쓰지 않고 인메모리로 측정.

**버그 발견·수정 1건**: 초판 스윕에서 MAX5 제외 임계값을 "그 달 보유 중인
~30종목" 내부에서 계산했다 - `build_selection_maxexcl.py`의 원래 정의("그 달
적격 유니버스 전체", ~800종목)와 달라, 이미 저PBR로 걸러진 좁은 표본의 자체
분포를 쓰는 오류였다. 수정 후 (nDrop=3, pct=0.8) 재현치가 기존 결합 실험
결과(CAGR 6.87%·MDD -18.90%·Sharpe 0.6809·청산 649건)와 소수점까지 정확히
일치 - 스윕 인프라 자체의 정확성 확인.

## 결과 (CAGR, 9격자 + 각 nDrop의 dropout-alone)

| nDrop\\pct | none(dropout만) | 0.7 | 0.8 | 0.9 |
|---|---|---|---|---|
| 2 | 6.52% | 6.57% | **7.74%** | 7.68% |
| 3 | 5.36% | 5.65% | **6.87%** | 6.63% |
| 5 | 4.84% | 5.18% | **5.97%** | 5.81% |

(baseline CAGR 4.72%)

## 판정

1. **시너지(초가산적 효과)는 nDrop 전체에서 재현된다** - 각 nDrop에서
   naive_sum(dropout_gap + maxexcl_gap) 대비 실제 combined_gap이 항상
   더 크다: nDrop=2 초과분 +0.27%p·nDrop=3 +0.56%p·nDrop=5 +0.18%p. 세
   경우 다 양(+)이지만 크기는 nDrop=3에서 가장 크다 - "결합이 상쇄되지
   않는다"는 결론은 견고, "얼마나 증폭되는가"는 파라미터에 따라 달라진다.
2. **percentile=80%가 세 nDrop 전부에서 국소최적**(70%·90% 둘 다보다 낫다)
   - 이전 세션이 임의로 고른 값이 아니라 이 좁은 격자 안에서는 일관되게
   최선이라는 뜻. 단 70%/80%/90% 세 점만 봤으므로 진짜 연속 최적점이
   80% 근방 어딘가라는 것 이상은 말할 수 없다.
3. **nDrop은 낮을수록(회전율을 더 강하게 제한할수록) 유리했다** - dropout
   단독 CAGR이 nDrop=2(6.52%) > nDrop=3(5.36%) > nDrop=5(4.84%)로 단조
   감소. 이전 세션이 쓴 nDrop=3은 이 격자 안에서 최선이 아니었다 -
   **nDrop=2 + pct=0.8 조합(CAGR 7.74%·Sharpe 0.7406)이 이 스윕 전체에서
   최선**(MDD만 nDrop=3·pct=0.8의 -18.90%가 nDrop=2·pct=0.8의 -19.40%보다
   근소하게 낫다).

## 한계

- 격자가 3×3으로 좁다 - nDrop<2(예: 1)나 percentile 극단값(0.6·0.95 등)은
  안 봤다. nDrop이 낮을수록 좋다는 단조 패턴이 nDrop=1까지 이어지는지,
  아니면 반전점이 있는지 미확인.
- naive-sum 비교에 쓴 maxexcl_gap은 percentile=80% 한 값만 재사용(baseline+
  maxexcl-alone을 70%·90%에서 따로 측정 안 함) - 시너지 크기의
  percentile별 분해는 이 스윕만으로는 안 나온다.
- 여전히 OOS(TRAIN/VALID/TEST) 분할 미검증 - 이 격자 전체가 같은 기간
  (2016~2026) 전체를 보고 고른 것이라 사후적으로 최적 파라미터를 고르는
  built-in look-ahead가 있다(다음 스텝이 OOS를 반드시 거쳐야 하는 이유).
- combined는 여전히 "연구 후보, production 미확정" - nDrop=2가 이 격자
  에서 이겼다고 그것으로 즉시 교체하지 않는다(OOS 없이는 과적합 파라미터
  선택일 수 있다).
