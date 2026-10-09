---
track: kr
factor: qullamaggie-breakout-forward
date: 2026-10-10
verdict: PREREGISTERED
reason: >-
  사전등록(동결). 쿨라마기 돌파(qullamaggie-breakout-results REJECT — 세 구간 net 양·N1 초과지만 TRAIN 하단 미달, 거래 154건)의
  같은 규칙을 앞으로 생기는 거래로만 다시 잰다. 기록 전용 — 점수·매매 불연결. 사용자 사전 위임(야간 자율 연구).
---

# 쿨라마기 돌파 forward — 사전등록

## 1. 규칙

- `qullamaggie_breakout.py` 의 정의를 **한 글자도 바꾸지 않는다**(사전등록 qullamaggie-breakout-preregistration-2026-10 §3, 커밋 f3d9fa76 의 코드).
- 대상 거래 = 진입일 ≥ **2026-10-12**(동결 다음 거래일). 같은 규칙의 과거 거래(154건)는 섞지 않는다.

## 2. 운영

- 월간 점검(A2a 증분 뒤): `python research/strategy-lab/qullamaggie_breakout.py --forward` → `reports/2026-10-qb-forward/trades.jsonl`(추적·커밋).
  닫힌 거래만 기록한다(진입일·종목·보유일·순수익). 같은 거래는 한 번만. 출력은 건수만(판정 전 성과 값을 보지 않는다).

## 3. 판정 (한 번)

- 시점: 닫힌 거래 **60건 ∧ 동결 뒤 24개월** 둘 다 찬 뒤 첫 월간 점검(현실적 예상 2029~2030, 연 15건 남짓). `--forward-judge` 는 그 전엔 거부한다.
- **REPLICATED** = 거래 순수익 월 평균 > 0 ∧ 6개월 블록 부트스트랩 90% 하단 > 0. 평균 > 0 이지만 하단 ≤ 0 → INCONCLUSIVE(연장 없음, 기록 종료). 평균 ≤ 0 → NOT REPLICATED.
- REPLICATED 여도 채택이 아니다 — 모의 슬리브 여부는 별도 GO.
