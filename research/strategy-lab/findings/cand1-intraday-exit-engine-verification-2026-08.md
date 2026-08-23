# CAND1 09:35 청산 엔진 확장 — MinuteProvider vs standalone 대조 (2026-08)

신호·진입·비용(thr=0.02, vthr=1.5, cost=20bp) 무변경. standalone 12804건(그리드 n_c0935) 각각의 청산가를 `engine/execution/intraday_exit.py`(MinuteProvider 경로)로 다시 조회해 대조한다.

**표본수 정정**: 기존 문서(`cand1-regime-conditional-2026-08.md`)의 13,329건과 이 문서의 12804건은 다르다 — 버그가 아니라 정의 차이다. 원 문서는 `entryDate`가 `calendar.json`(2026-08-14까지만) 밖으로 나가 매핑이 안 된 신호도 baseline 총계에는 포함하고 regime 매칭(849건)만 실패로 뺐다. 이 문서는 MinuteProvider 조회 자체가 entryDate 없이는 불가능해 그 525건을 baseline 정의 단계에서부터 제외했다 — 신호·진입·비용은 동일, **표본 범위(calendar 끝단)만 다르다.**

## 1. 커버리지

| 항목 | 값 |
|---|---|
| standalone 전체 거래수 | 12804 |
| 분봉 캐시 범위 밖(진입일이 2025-08-08~2026-08-21 밖) | 0 |
| 캐시 범위 안인데 MinuteProvider 09:35 결측 | 2302 |
| 양쪽 다 값 있음(대조 가능) | 10502 (82.0%) |

## 2. 가격 레벨 일치 (양쪽 다 값 있는 10502건)

| 기준 | 건수 | 비율 |
|---|---|---|
| 완전 일치(오차 <1e-6%) | 10482 | 99.81% |
| 근접 일치(오차 <0.01%) | 10482 | 99.81% |

## 3. 집계 재현 (같은 10502건 부분표본 안에서 그리드 vs MinuteProvider)

| 소스 | 거래수 | 승률 | PF | gross(bp) | net(bp) | MDD(%) |
|---|---|---|---|---|---|---|
| 그리드(n_c0935, 원본) | 10502 | 54.5% | 1.43 | 43.74 | 23.74 | -22.91 |
| MinuteProvider(신규) | 10502 | 54.4% | 1.42 | 42.41 | 22.41 | -23.52 |

## 4. 참고: entryDate 매핑 가능한 12804건 전체(부분표본이 아니라 전체, §1 정정 참고)

| 거래수 | 승률 | PF | net(bp) |
|---|---|---|---|
| 12804 | 54.6% | 1.43 | 21.65 |

## 5. 판정

가격 근접일치율 99.81%, 부분표본 net 차이 -1.33 bp(그리드 대비) → **PASS**

판정 기준(사전 설정, 결과 보고 정하지 않음): 근접일치율 >99% AND net 차이 <2bp.

## 검증 가능한 근거 목록

- `engine/execution/intraday_exit.py` — 신규 확장 모듈(무변경 대상: executor.py·contracts.py)
- `tests/test_intraday_exit.py` — PIT·결측·공식·독립성 pytest 10건 통과
- `analyze_cand1_regime_conditional.py` — standalone baseline 원출처(무변경)
- 본 스크립트 `verify_cand1_intraday_exit_vs_standalone.py` — 재실행하면 동일 결과
