---
track: kr
factor: video-strategies-parked
date: 2026-08-22
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "영상전략 보류 항목 기록 - V4는 swing 탐지 정의 미확정이라 1차 관측 음수를 실패로 확정 불가, C등급 DATA GAP(V6 매집가)은 해소 - 재개는 사람(Claude·사용자) 설계 결정 대기"
---

# Parked — 보류 항목 (video-strategies-2026-08)

작성 2026-08-22. B/C 등급 전략의 "왜 지금 안 되는지"만 기록한다.
데이터/결정이 생기면 재개할 수 있게 근거 파일을 함께 남긴다.

## V4 — Fibonacci 38.2/61.8 + 지지/저항 (B)

- **데이터**: 문제 없음 — OHLC는 `research/strategy-lab/.cache/a2a_parquet`로 충분하다.
- **왜 지금 확정 못 하나**: swing point 탐지 방법이 영상에 없다([UNSPECIFIED], 지시서가
  명시한 이 후보의 핵심 리스크). 1차 관측(`findings/v4-fib-sr`)은 인과적 대칭창 pivot
  (L=3, k+L봉 종가 확정)이라는 임시 정의로 수행했고 결과는 전 호른즈 미세 음수였다.
  그러나 swing 정의(zigzag %역치, ATR 기반 창, pivot L 값 등)가 바뀌면 leg 구성 자체가
  달라져 결과가 바뀔 수 있다 — 현재 음수를 "전략 실패"로 확정할 수 없고,
  양수 가능성도 주장할 수 없다.
- **재개 조건**: 사람(Claude·사용자)의 설계 결정 — (1) swing 탐지 규칙 확정 또는
  (2) 영상 원본 확인. 결정 후 `v4_fib_confluence_signal_study.py`의 PIVOT_L·zigzag
  수용 규칙만 교체해 재실행하면 된다(측정 관례는 변경 불필요).

## C등급 — 해당 없음

모든 후보의 필요 데이터는 저장소에 존재한다. 유일한 DATA GAP 후보였던 V6 "매집가"는
원본 백필(`data/backfill/supplyDemand/a4/*.jsonl.gz`)에 투자자별 매수 금액·수량이
모두 있는 것으로 확인돼 해소됐다(audit.md V6 참조).
