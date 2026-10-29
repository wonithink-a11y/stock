---
track: crypto
factor: hash-ribbons
date: 2026-10-30
verdict: PREREGISTERED
criteria_version: research-only
conditions: ["blockchain.info 공개 차트 hash-rate(일별 추정치, 키 없음) · 바이낸스 BTCUSDT 1시간 봉 00:00 UTC 시가", "항복 국면 C(d) = 해시레이트 30일 단순평균 < 60일 단순평균(Hash Ribbons, C. Edwards 2019 정의 그대로)", "공표 지연 1일: d 의 국면 → d+2 하루 수익(O(d+3)/O(d+2) − 1)", "H1 = 항복 날 vs 아닌 날 일수익 차(Welch t), 바닥선 = 국면 마스크 원형 이동 500회 95% · ECONOMIC = 좋은 국면만 1x 보유 규칙 ΔSharpe(편도 5bp·스트레스 10bp) > 0", "TRAIN 2018~2022 / VALID 2023 / TEST 2024-01 ~ 2026-09"]
reason: >-
  신호: (미측정) · 경제성: (미측정). 질문 — "채굴자 항복 국면(해시레이트 30일선이 60일선 아래)에 BTC 수익이 달라서, 국면에 따라 들고 있거나 쉬면 위험 대비 성과가 나아지는가".
  사용자 위임(2026-10-30 밤) 후보 3번.
---

# 해시 리본(채굴자 항복 국면) → BTC — 사전등록 (2026-10-30)

> **동결.** 이 커밋 이후 정의·창·지연·구간·비용·셀을 바꾸지 않는다. 결과는 `hash-ribbons-results-2026-10.md`.
> 코드 `research/strategy-lab/futures/hash_ribbons.py`(다음 커밋, 해시는 결과 파일 머리말에).

## 0. 선행 지식 (결과 아닌 것만)

- Hash Ribbons(Charles Edwards, 2019): 해시레이트 30일선 < 60일선 = 채굴자 항복, 30일선이 다시 위로 + 가격 10일선 > 20일선 = '매수 신호'. 공개 지표로 널리 쓰인다.
  원 주장은 "매수 신호 뒤 수익이 좋다"인데 신호는 1년 1~2번이라 통계 검정이 불가능하다 → **판정은 국면(H1)으로만, 매수 신호(H2)는 기록 전용**.
- 이 저장소: 온체인 지표 연구 0건. 방향은 미리 정하지 않는다 — 항복 국면이 '나쁜 날'(쉬기)일 수도 '바닥 근처'(들고 있기)일 수도 있다. TRAIN 부호가 정한다.
- blockchain.info 해시레이트는 블록 수·난이도로 추정한 값이라 하루 단위로 시끄럽다(30·60일 평균이 그것을 줄인다). 과거 값의 사후 수정 여부는 확인 못 함 → 한계.
- **현실적 기대: REJECT 또는 INFORMATION.** 국면은 길게 이어져 독립 관측이 적다(원형 이동 바닥선이 이를 반영한다).

## 1. 데이터

- `GET https://api.blockchain.info/charts/hash-rate?timespan=all&format=json&sampled=false` → (일 시작 UTC 초, TH/s). 2009~2026-10. 저장 `data/crypto/onchain/hashrate.json`(gitignore).
- BTC: `data/crypto/cbprem/bn_btc.parquet` 00:00 UTC 시가 O(t).

## 2. 정의

- hr(d) = 그날 값. 빠진 날은 결측(채우지 않음). S30(d)·S60(d) = 직전 30·60일(d 포함) 평균, 유효 25·50 이상.
- C(d) = S30(d) < S60(d). d 의 값은 d 가 끝난 뒤 공표되므로 **d+2 하루**에 적용한다: 관측 r = O(d+3)/O(d+2) − 1, 관측일 = d+2.

## 3. 판정 (crypto-dvol V1 과 같은 틀)

- 통계량: TRAIN 의 항복 날 평균 − 아닌 날 평균(Welch t). 바닥선 = 마스크를 TRAIN 안에서 무작위 원형 이동(30일 이상) 500회(seed 20261101)한 |Welch t| 의 95%.
- INFORMATION: TRAIN |t| ≥ 바닥선 ∧ VALID·TEST 의 차이가 TRAIN 과 같은 부호.
- ECONOMIC: 그리고 VALID+TEST 에서 '좋은 국면(TRAIN 부호가 가리킨 쪽)만 1x, 나머지 0x' 규칙 Sharpe 가 항상 1x 보다 크다 — 편도 5bp·10bp 두 비용 모두.
- ROBUST: 그리고 VALID+TEST ΔSharpe 가 같은 원형 이동 500회 분포의 95% 위.
- 결과 표: 일수·항복 비율·차이 bp·t(구간별) · 규칙/항상보유 연율 수익·변동성·MDD·Sharpe · 시기 칸 ~2023 / 2024 / 2025~ · 연도별.

## 4. 기록 전용 (판정 불사용)

1. H2 매수 신호(항복 뒤 S30 이 S60 위로 올라선 뒤 처음으로 가격 10일 평균 > 20일 평균인 날, 다음 항복 전 1회) — 날짜 목록, 뒤 30·60·90일 BTC 수익과 같은 기간 아무 날 평균.
2. 지연 0일(d+1 적용) 같은 통계량.
3. 항복 국면 길이 분포·연도별 비율.

## 5. 하지 않는 것

창(30·60)·지연·가격 확인 조건 변경, 다른 해시레이트 출처로 교체, 결과 뒤 셀 추가, 비용 변경, 구간 재절단.
