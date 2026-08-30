---
track: kr
factor: pbr-dropout-turnover-limit
date: 2026-08-26
verdict: HOLD
criteria_version: backfill-v1
conditions: ["Qlib TopkDropoutStrategy 방식", "nDrop=3", "월별 최대 nDrop개 교체", "continuousHoldOnRenewal"]
reason: "회전율 제한으로 CAGR +0.64%p·MDD 개선·Sharpe +0.0345 전부 같은 방향 개선·2022 몰빵도 아님 - 1회 실행·nDrop 1개·OOS 미검증이라 아직 채택 근거 아님"
cagr: 5.36
sharpe: 0.4901
mdd: -21.42
---
# PBR — Qlib TopkDropoutStrategy 방식(회전율 제한) 적용 결과 (2026-08-26)

`findings/github-strategy-sources-usability-2026-08.md`가 찾은 유일한
"진짜 새 축" 후보를 실제로 구현·검증했다. `strategies/pbr_value_v1/
build_selection.py`는 매달 top-30을 완전히 새로 뽑아 전월 보유를 전혀
안 본다는 걸 코드로 확인했고, Qlib(microsoft/qlib)의
`TopkDropoutStrategy`(topk=50, n_drop=5)가 쓰는 "매달 최대 n_drop개만
교체" 방식을 그대로 가져와 `pbr_value_v1_dropout`(topN=30, nDrop=3, 같은
10% 비율)으로 구현했다.

## 결론: 개선 확인, 단 1회 실행·1개 파라미터 값 기준

| | baseline(pbr_value_v1) | dropout(nDrop=3) | 차이 |
|---|---|---|---|
| CAGR | 4.72% | **5.36%** | **+0.64%p** |
| MDD | -21.70% | **-21.42%** | +0.28%p 개선 |
| Sharpe | 0.4556 | **0.4901** | +0.0345 |
| 청산 거래 | 756건 | **449건** | -40.6% |
| 월평균 신규진입 종목수 | 6.08 | 3.65 | -40.0% |

**3개 헤드라인 지표(CAGR·MDD·Sharpe)가 전부 같은 방향으로 개선**됐다 —
이 프로젝트가 반복 겪은 "한 지표는 좋아지고 다른 지표는 나빠지는"
트레이드오프(예: LOWMOM60 노출 오버레이 CAGR↑ MDD↓) 패턴이 아니다.

연도별로도 한 해에 몰리지 않는다: 11개 연도 중 7개(2016·2021·2022·
2023·2024·2025·2026)가 우위, 4개(2017·2018·2019·2020)가 열위 -
PBR-vs-EW 초과수익이 2022년 단독 98.6%였던 것과는 다른 패턴이다.

## 방법론 — 이전 실수를 반복하지 않기 위한 선택

`run_pbr_value_v1.py`가 쓰는 realized-pnl-at-exit-event 방식은 안 썼다 -
그 방식은 연속보유 병합 포지션의 손익을 마지막 청산일이 속한 해에 몰아
왜곡한다는 게 2026-08-22에 이미 밝혀졌다(PBR 정본 CAGR을 Sharpe 2.25
→0.46으로 정정하게 만든 바로 그 문제). 대신 `pbr_vs_ew_monthly_mtm.py`의
`run_and_measure()`(월별 시가평가)를 그대로 재사용해 baseline·dropout
둘 다 같은 방법으로 쟀다 - 이 스크립트로 재현한 baseline 수치
(CAGR 4.72%·MDD -21.70%·Sharpe 0.4556)가 CLAUDE.md 상태블록 최종
정정본과 정확히 일치함을 먼저 확인한 뒤 비교를 신뢰했다.

## 왜 개선됐는가 — 메커니즘

`policy.json`의 `continuousHoldOnRenewal: true`(pbr_value_v1과 동일)
덕분에 dropout이 유지시킨 종목은 청산-재진입 없이 원래 진입가로 계속
보유된다. 그래서 회전율이 40% 줄면 왕복비용(30bp/회)이 그만큼 줄고,
그게 그대로 net 성과 개선으로 이어진다 - 이 프로젝트가 반복 관측해온
"오프라인 사전점검 → 실엔진에서 비용에 침식"과 정반대 방향의, 비용
구조를 직접 겨냥한 개선이다.

## 한계 — 아직 채택 근거로 쓰지 않는다

- **1회 실행, nDrop=3 하나만 테스트**. 다른 nDrop 값(1·2·5 등)에서도
  같은 방향인지 스윕 안 했다.
- 여전히 `runClassAllowed: ["SMOKE"]`(A1A_ONLY, 생존편향 있음) - baseline
  자체도 아직 PRIMARY 승격 안 됐다.
- Out-of-sample 분할(TRAIN/VALID/TEST)로 재확인 안 함 - 이 프로젝트가
  Opening Fade·REV20 등에서 반복 겪은 "TRAIN/VALID 양호 → TEST 반전"
  패턴이 여기서도 일어날 수 있는지 아직 모른다.
- LOWMOM60에는 아직 적용 안 함(사용자 지시: "PBR부터").

## 파일

- `strategies/pbr_value_v1_dropout/`(policy.json·rule.py·
  build_selection_dropout.py·selection.json) - rule.py는 pbr_value_v1과
  완전 동일(무변경 복사), 차이는 selection.json 생성 로직뿐
- `build_selection_dropout.py --selftest`: dropout 알고리즘 자체를
  합성 데이터로 8건 검증(첫 달=순수 top-N과 동일·변동없음 유지·정확히
  nDrop건만 교체·강제이탈은 nDrop과 무관 등) - 전부 통과
- `run_pbr_dropout_vs_baseline_mtm.py` - 이 문서의 실행 스크립트
- `reports/2026-08-26-pbr-dropout-vs-baseline-mtm/
  pbr-dropout-vs-baseline-mtm.json` - 원자료(연도별 수익률 포함)
- 기존 회귀 143건 전체 재확인(무변경 통과) - engine/공유 코드 미변경 확인