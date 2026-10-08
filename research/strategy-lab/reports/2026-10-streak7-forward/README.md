# 연속 상승 7일 forward 관찰 기록

- 사전등록: `findings/streak7-forward-preregistration-2026-10.md` (1f415ef0) · 기록기: `run_streak7_shadow.py`
- `observations.jsonl` — 추가 전용(수정·삭제 금지). 줄 종류: signal(신호) · mature(20거래일 성숙) · void(사건에서 빠짐). 동결일 이후 신호(≥ 2026-10-09)만. 아직 신호가 없으면 파일이 없다.
- `bridge.jsonl` — 참고 표본(2026-01-15 ~ 2026-10-08 신호, 성숙분) 1회 기록. **판정에 쓰지 않는다.**
- `judgment.json` — 판정 시점(성숙 500건·24개월, 연장 시 800건·36개월)에 `--judge` 가 1회 생성. 그 전에는 없다.
- 판정 시점 전에 성과 값을 계산·발표하지 않는다(사전등록 §4).
