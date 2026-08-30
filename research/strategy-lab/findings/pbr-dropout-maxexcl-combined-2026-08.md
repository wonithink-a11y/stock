---
track: kr
factor: pbr-dropout-maxexcl-combined
date: 2026-08-26
verdict: HOLD
criteria_version: backfill-v1
conditions: ["pbr_dropout", "pbr_maxexcl", "combined_overlay"]
reason: "dropout+MAX제외 결합이 단순 합산 가정을 넘어선 초가산적 개선(CAGR +2.15%p)이나 단일 파라미터 조합·1회 실행으로 research 후보에 그침 - production alpha 미확정"
cagr: 6.87
sharpe: 0.6809
mdd: -18.90
n: 649
---
# PBR dropout + MAX제외 결합 실험 — 단순 합산보다 큰 개선 (2026-08-26)

세션인수인계-2026-08-26.md §5-1(두 실험의 결합, "단순 합산 가정 금지")을
확인. `strategies/pbr_value_v1_combined/`(로컬 전용, 아래 §3 참고) —
`build_selection_combined.py`가 `pbr_value_v1_maxexcl`과 완전히 같은
MAX제외 로직(MAX5 상위 20% 대체 없이 제외)을 `pbr_value_v1_dropout`의
selection.json(회전율 제한이 이미 적용된 매달 보유목록) 위에 씌운다. 순서를
고정한 이유: MAX제외를 dropout보다 먼저 적용하면 dropout의 nDrop 예산 계산
자체가 달라지므로, 두 실험이 각각 독립 검증한 selection.json을 그대로
재사용하려면 "dropout이 먼저 확정 → 그 위에 MAX제외" 순서여야 한다.

## 결과 (같은 MTM 방법론, `pbr_vs_ew_monthly_mtm.py`)

| | baseline | dropout | maxexcl | **combined** |
|---|---|---|---|---|
| CAGR | 4.72% | 5.36% | 5.67% | **6.87%** |
| MDD | -21.70% | -21.42% | -20.80% | **-18.90%** |
| Sharpe | 0.4556 | 0.4901 | 0.5814 | **0.6809** |
| 청산거래 | 756건 | 449건 | 882건 | 649건 |

## 판정 — 단순 합산을 넘어선다(초가산적)

```
CAGR:   dropout(+0.64%p) + maxexcl(+0.95%p) = 단순합산 +1.59%p
        combined 실제 = +2.15%p  →  단순합산보다 +0.56%p 더 큼
Sharpe: dropout(+0.0345) + maxexcl(+0.1258) = 단순합산 +0.1603
        combined 실제 = +0.2253  →  단순합산보다 +0.065 더 큼
MDD:    개별 최선(maxexcl -20.80%)보다 combined(-18.90%)가 더 낮다
```

세 지표(CAGR·Sharpe·MDD) 전부에서 결합이 단순 합산 가정을 넘어선다 —
상쇄(각자의 효과가 겹쳐서 줄어듦)가 아니라 **오히려 증폭**됐다. 두 필터가
서로 다른 경로로 작동한다는 정황과 부합한다: dropout은 회전율을 줄여
저PBR 보유의 "질"(선정 정확도가 아니라 유지 안정성)을 높이고, MAX제외는
그렇게 안정적으로 유지되는 보유 종목 중 복권형 종목을 추가로 걸러낸다 —
같은 종목 풀에 서로 다른 축으로 필터링이 적용되면서 개별 적용보다 더 깨끗한
포트폴리오가 남은 것으로 해석된다.

거래건수(756→449→882→649)는 dropout이 회전율을 크게 줄였다가(449) 그 위에
MAX제외를 얹으면 다시 늘어난다(649) — MAX5는 월별로 변하는 종목별 특성이라
"이번 달엔 MAX 상위였다가 다음 달 아니게 되는" 종목이 dropout의 유지 로직과
별개로 추가 회전을 유발하기 때문. 그래도 baseline(756)보다는 여전히 적다.

## 한계

- 여전히 1회 실행, 단일 파라미터 조합(nDrop=3, exclusion percentile 80%)만
  테스트 - 세션인수인계-2026-08-26.md §2.3의 다른 한계(T1/T3 분해는
  findings/pbr-dropout-maxexcl-t1t3-decomposition-2026-08.md로 이미 해소,
  OOS 분할·파라미터 스윕은 여전히 미검증)가 남는다.
- "초가산적"이라는 결론이 이 특정 파라미터 조합·이 기간에 국한된 것인지,
  파라미터를 바꿔도 재현되는 패턴인지는 스윕 없이는 모른다.
- combined 자체도 여전히 "연구 후보, production alpha 미확정" 분류 -
  이 결과 하나로 채택 근거를 만들지 않는다.
