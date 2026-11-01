---
track: kr
factor: kr-static-vi-forward
date: 2026-11-01
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["사건 정의·진입·청산 = kr-static-vi-proxy(ebccca5·dddd05e) VU 그대로(09:01~15:10 시가 +10% 첫 도달 → 3분 뒤 봉 종가 → 당일 마지막 봉 종가, 잠김 제외, 하루 평균 = 한 관측)", "VU_L = 전일 분봉 거래대금 상위 200 (kr-static-vi-liquid fb8afed·839625f 그대로)", "관측일 ≥ 2026-11-02 · VM ~/minute-raw 의 manifest 통과 날만 · 처음 계산한 값 고정(원장 덮어쓰기 금지)", "방향 고정 = 숏(원 연구 TRAIN 부호) · 비용 33.5bp · 67bp", "판정 1회: 관측일 100 ∧ 2027-05-03 이후, INCONCLUSIVE 면 200 ∧ 2027-11-01 까지 1회 연장"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "장중 시가 +10% 첫 도달 뒤 종가까지 빠지는 현상(VU ROBUST, 2025-08~2026-10)이 앞으로도 같은 크기로 이어지는가".
  사용자 GO(2026-11-01 "1번 진행"). 기록 전용 — 점수·매매 불연결, 알림의 맥락 문구는 원 연구 근거로 따로 붙였다.
---

# 정적 VI 근사 VU forward 기록 — 사전등록 (2026-11-01)

> **동결.** 이 커밋 뒤 사건 정의·문턱·방향·비용·판정 시점·판정 규칙을 바꾸지 않는다. 통과해도 매매 반영은 🔴 별도 GO.

## 0. 지금 아는 것

- 원 연구(kr-static-vi-proxy-results-2026-11, 확정): VU 일 평균 TRAIN −138 · VALID −155 · TEST −208bp, 숏 OOS net33.5 +154bp(t 10.4). VU_L(전일 거래대금 상위 200)도 TEST −268bp.
- 표본은 2025-08~2026-10 한 장세(대형주·반도체 쏠림, 개인 테마 순환)다. forward 의 질문은 '다른 달에도 이어지는가' 하나다.

## 1. 기록

- VM 타이머 `vi-forward`(평일 20:30 KST)가 `~/minute-raw` 의 manifest 통과 날 중 아직 안 쓴 날(≥ 2026-11-02)을 계산해 `~/collector-venv/vi-forward/daily.jsonl` 에 한 줄씩 덧붙이고
  `/srv/stock-data/bundles/_status/vi-forward.jsonl` 로 복사한다(클라우드가 `/research-data/` 로 읽는다). 줄 = {day, VU: {n, mean_bp, mean_1519_bp}, VU_L: {…}, VU_S: {…}, skipped}.
- 월간 점검이 그 파일을 받아 `reports/2026-11-kr-static-vi-forward/daily.jsonl` 로 커밋한다. 이미 있는 날은 고치지 않는다(다르면 drift.jsonl 에 기록).

## 2. 판정 (1회)

- 시점: VU 관측일 100 ∧ 2027-05-03 이후. 그 전 `--judge` 는 코드가 거부(건수만 출력).
- VU(판정 셀): 숏 일 수익 = −mean_bp.
  **CONFIRMED** = 숏 평균 − 33.5 > 0 ∧ t(숏 − 33.5) ≥ 2 · **FADED** = 숏 평균 ≤ 0 · 그 밖 **INCONCLUSIVE** → 관측일 200 ∧ 2027-11-01 에 한 번 더(같은 규칙, 그때 못 가리면 INCONCLUSIVE 종결).
- VU_L·VU_S·15:19 청산은 기록 전용(같은 식으로 계산만).

## 3. 하지 않는 것

문턱(±10%)·진입 지연·청산 시각·컷(200) 변경 · 롱 뒤집기 · 중간 숫자로 판정 · 알림 문구를 forward 결과로 바꾸기(판정 전).

## 동결

이 커밋 뒤 문턱·창·셀·비용·판정 규칙을 바꾸지 않는다.
