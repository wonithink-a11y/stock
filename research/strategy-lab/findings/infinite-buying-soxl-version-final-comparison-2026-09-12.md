# SOXL 단일종목 V2.1 vs V3.0 vs V4.0 최종 비교 (2026-09-12)

`infinite-buying-tqqq-version-final-comparison-2026-09-12.md`(TQQQ) 후속 — 같은 조건을
SOXL(base=20, 3A 확정 12개 episode)에 적용. 스크립트를 `--ticker`/`--base` 파라미터화
했고(`infinite_buying_tqqq_version_episode_compare.py`), TQQQ 재실행이 기존 결과와
정확히 일치함을 확인한 뒤(회귀 없음) SOXL을 돌렸다.

```bash
python research/strategy-lab/infinite_buying_tqqq_version_episode_compare.py --ticker SOXL --base 20
```

## 결과 — TQQQ와 같은 패턴이 더 뚜렷하게 나온다

```
             episode평균CAGR   최악episode CAGR      최악episode MDD   전략 회복실패
V2.1         +14.92%p          -4.11%(2015-06)        25.1%            1/12
V3.0         +18.37%p          -11.78%(2015-06)        31.1%            2/12
V4.0         +32.01%p          -3.16%(2026-06, 진행중)  69.3%            1/12
```

**V2.1·V3.0이 같은 episode(2015-06-01, 낙폭 63%, 중간 정도 조정)에서 동시에
실패한다** — V2.1 -4.11%, V3.0 -11.78%, 둘 다 "가격은 회복했는데 계좌는 손실".
같은 episode에서 V4.0 은 +11.27%로 정상 회복했다. TQQQ의 2012년 사례와 같은
모양이다 — **중간 정도 조정에서 보수적 버전이 오히려 반등 참여 부족으로 실패한다.**

V4.0의 유일한 "회복실패"는 **2026-06-22 episode(아직 진행 중, 미회복)** 뿐이다 —
이건 완결된 실패가 아니라 그냥 아직 안 끝난 것뿐이라 TQQQ 의 0/16 과 사실상 같은
성격이다(진짜 위험 신호가 아니다).

### 최대 위기(2021-12-27, 낙폭 90.5%, 1274일 만에 회복)

```
V2.1  +9.95%   MDD 25.1%
V3.0  +6.81%   MDD 30.4%
V4.0  +15.45%  MDD 69.3%(저점 현금비중 2%)
```

셋 다 결국 플러스로 끝났지만 **V4.0 이 가장 높은 수익을 내면서 가장 크게(69.3%)
흔들렸다** — 저점 현금비중 2%(3B/3C에서 이미 확인한 그 수치)가 여기서 다시 보인다.
1274일(3.5년)을 -69% 근처로 버텨야 이 수익이 나온다는 뜻이다.

## TQQQ findings와 결합한 결론

두 종목 모두 같은 그림이다:

```
V4.0   최악 episode 결과가 오히려 덜 나쁘다(TQQQ +4.21% vs V2.1 -12.47%,
       SOXL -3.16%[진행중] vs V2.1 -4.11%[완결실패]) — 대신 MDD 가 압도적으로 크다
       (TQQQ 50.8%, SOXL 69.3%)
V2.1/V3.0   MDD 는 작지만(TQQQ 35~37%, SOXL 25~31%) 중간 정도 조정에서
       "가격은 회복했는데 계좌는 손실"인 완결된 실패 사례가 있다
       (TQQQ 2012년 둘, SOXL 2015년 하나 — 둘 다 V2.1·V3.0 동시 실패)
```

**TQQQ findings의 결론이 SOXL에서도 재현된다** — "V4.0의 위험은 영구 손실이
아니라 버티는 동안의 극심한 흔들림이고, V2.1/V3.0의 안전함은 흔들림은 작지만
중간 규모 조정에서 반등을 놓쳐 완결 손실로 끝날 수 있다는 대가가 있다"는 패턴이
종목을 바꿔도 그대로 나온다. 판정(어느 쪽을 실제로 쓸지)은 TQQQ findings와 동일한
이유로 내지 않는다 — 사용자의 위험 감내 방식(고정시점 평가 vs 완주 능력)에 달렸다.

## 재현

```bash
python research/strategy-lab/infinite_buying_tqqq_version_episode_compare.py --selftest
python research/strategy-lab/infinite_buying_tqqq_version_episode_compare.py --ticker SOXL --base 20
```
