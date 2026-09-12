# 3A — 실제 Drawdown Episode 자동 탐지기 (2026-09-12)

`infinite-buying-crisis-path-decomposition-2022-2026-09-12.md` 후속. 2022 하나로
끝내지 않고 TQQQ·SOXL 전체 역사(2010~2026)에서 고점→낙폭→저점→회복 episode 를
자동 탐지한다. **전략 코드(엔진)를 전혀 참조하지 않는다** — 종가만 본다
(`infinite_buying_drawdown_episodes.py`). episode 확정과 전략 성과 관찰을 분리해
selection bias 를 줄이는 게 목적이다(3B 에서 전략 성과를 보고 episode 를 다시
고르지 않는다).

## 임계값 25% — 사후 최적화 아님

20%/25%/30% 세 값으로 TQQQ 를 돌려 대형 episode(2018·2020·2022) 가 전부 그대로
남는 것을 확인했다(경계에 있는 작은 episode 만 들고 난다: 20%→21건, 25%→16건,
30%→13건). 즉 25% 는 결과를 보고 맞춘 값이 아니라, 그 안 어디를 잡아도 답이
바뀌지 않는 안정 구간에서 고른 라운드 넘버다.

## 결과 (임계값 25%)

- **TQQQ**: 16건(회복 15 · 미회복 1)
- **SOXL**: 12건(회복 11 · 미회복 1)

알려진 사례가 전부 잡힌다: 2020 코로나(TQQQ -69.9%/30일, SOXL -80.4%/30일),
2018년 4분기(TQQQ -58.1%, SOXL -66.7%), 2022 크래시(TQQQ -81.8%/404일,
SOXL -90.5%/291일). 회복 기간 편차가 크다 — 짧으면 12~44일, 길면 714일
(TQQQ 2022)·1274일(SOXL 2021-12 시작 구간) — 3C 의 "매도 후 회복 여유기간"
가설을 검증하기에 좋은 다양성이다.

## 커밋 전 확인 — 중복 집계(장기 하락 중 중간반등을 별도 episode 로 세는 문제) 없음

구조상 `peak_price` 는 episode 진행 중에는 갱신되지 않고 원래 고점 수준까지
완전히 회복해야만 episode 가 닫힌다 — 중간반등이 원고점에 못 미치면 새 episode
를 만들 자리 자체가 없다. 이걸 실측으로 못 박았다(`--selftest`, 6/6):

1. 합성 케이스 — 고점100 → -40%(임계 넘음) → 중간반등80(원고점 미달) → 재하락(더
   깊은 저점30) → 완전회복101. 결과: episode 1개, trough=30(중간반등 80으로
   안 되돌아감), 회복가=101. 기대대로.
2. 실제 데이터 겹침 검사 — TQQQ·SOXL 각각 25% 임계 episode 목록이 서로 겹치는
   구간이 없음을 전수 확인.

## 재현

```bash
python research/strategy-lab/infinite_buying_drawdown_episodes.py           # TQQQ+SOXL, 25%
python research/strategy-lab/infinite_buying_drawdown_episodes.py --ticker SOXL --threshold 0.30
python research/strategy-lab/infinite_buying_drawdown_episodes.py --selftest # 6/6
```

## 판정 — 3A PASS

임계값·탐지 로직 추가 조정 안 함(더 만지면 오히려 근거 없는 조정이 된다).
**strategy-independent detector, 25% threshold, 20/25/30 sensitivity 확인, 중복
집계 없음 — 이 네 가지를 이 커밋의 근거로 남긴다.**

## 다음 (3B, 미착수)

확정된 episode 목록을 그대로 V4.0 trace 에 매핑한다 — episode 를 전략 성과에
맞춰 다시 고르지 않는다(가격→episode 확정→trace 매핑→성과 관찰, 이 순서 고정).
episode 별 CAGR 하나가 아니라 **"episode 회복기간" × "후반전 매도 이후 남은
기간" × "V4.0 이 실제로 현금화한 정도"** 세 변수를 연결해서 2022 에서 나온 가설
("후반전 매도가 유리하려면 그 뒤 회복할 시간이 있어야 한다")이 다른 episode
에서도 반복되는지 본다.
