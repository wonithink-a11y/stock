# DEEPSEEK-1 — REV20 결합 견고성 검증 (비용×유동성×가격 동시 적용)

```
발행   2026-08-19 · Claude
대상   DeepSeek (독립 검증 — research/strategy-lab/ 안에서 스크립트 확장은 가능하나
       production 코드(lib/·scripts/·config/)·정책 파일은 건드리지 않는다)
선행   research/strategy-lab/reports/2026-08-18-strategy-candidates/README.md
       (이 문서의 §5.2·§5.4·§9가 이번 과제의 근거)
```

## 배경

2026-08-18 전략 후보 리포트(위 README)가 Momentum/Breakout/Pullback/MeanReversion
네 전략군을 독립 검증했다. 그 중 **REV20(20일 급락 상위 30종목 매수)**이 유일하게
생존편향을 걷어내도 성과가 개선되는 후보였다(A1A_ONLY +3.5% → A1A_A1B_MERGED +6.7%,
상장폐지 508종목 포함 시).

문제는 비용·유동성·가격 필터를 **한 번에 하나씩만** 테스트했다는 것이다:

| 조건 | CAGR | 비고 |
|---|---|---|
| baseline (30bps, 필터 없음, MERGED) | +6.7% | README §5.4 |
| cost 150bps (단독) | -9.7% | README §5.3, 유니버스 불명(A1A_ONLY로 보임) |
| minTurnover≥1천만원 (단독) | -0.6% | README §5.2, A1A_ONLY 기준 |
| minPrice≥5,000원 (단독, MERGED) | -7.0% | README §5.4 |

세 조건을 **동시에** 걸었을 때 어떻게 되는지가 안 나와 있다. 실제 매매라면 세 제약이
전부 걸린다 — 슬리피지 있는 비용, 유동성 확보, 저가주(관리종목·품절주 위험) 회피를
동시에 적용해야 하는데, 지금 수치만으로는 "REV20이 현실적 제약에서도 살아남는지"를
답할 수 없다. 이 리포트 §9도 스스로 이걸 "다음 라운드 검증 항목"으로 남겨뒀다.

## 재사용할 코드

새로 짤 필요 없다. `research/strategy-lab/lowmom60_survivorship.py`의
`run_backtest()`(85~163행)가 이미 `factor`·`min_price`·`min_turnover`·`cost_bps`
네 인자를 전부 받는다. `main()`(170행~)이 이 함수를 REV20·MERGED 조합으로 이미
호출한 전례가 있다(208~224행) — 그 호출부만 조합을 늘리면 된다.

```python
# 예시 — main() 안에 이런 호출을 추가하면 됨
run_backtest(merged, rebalance_dates, factor="rev20", ascending=False,
             min_price=5000, min_turnover=100_000_000, cost_bps=90)
```

## 확인해야 할 것

```
1  cost_bps만 60·90으로 올렸을 때 (MERGED, 필터 없음) CAGR — 개별 단독 재확인
2  min_turnover=1억(README 단위 재확인 — "1억"이 원/일인지 재검토) 단독 (MERGED) CAGR
3  cost 60bps + min_turnover 1억 결합 (MERGED, minPrice 없이) — 살아남는가
4  cost 60bps + min_turnover 1억 + min_price 5,000 결합 (MERGED, 최악 시나리오) — CAGR
5  minPrice≥5,000에서 손실로 뒤집히는 원인 — n_selected_rows·연도별(yearly) 분해로
   "표본이 줄어 통계가 불안정해진 것"인지 "특정 연도·소수 종목이 무너진 것"인지 구분
6  (여력이 되면) LOWMOM60도 같은 결합 조건에서 재확인 — 이미 minPrice 단독으로 붕괴가
   확인됐으므로(-5.8%) 결합해도 마찬가지인지만 짧게 확인
```

## 하지 말 것

```
✗ lib/·scripts/·config/ 등 production 경로를 건드리지 마세요
✗ "REV20을 채택하자/말자"는 결론을 내지 마세요 — 수치와 원인만 보고한다.
  채택 여부는 사용자 판단이다
✗ git commit·push 하지 마세요. research/strategy-lab/ 안에 결과 파일을 새로
  만드는 것 자체는 괜찮다(기존 리포트들도 그렇게 쌓여 있다) — 다만 커밋은 Claude가
  검토 후 한다
✗ A4(수급) 결합은 이번 과제 범위 밖입니다(README §8이 이미 "데이터 부재로 검증
  불가"라고 확정함) — 재조사하지 마세요
```

## 산출 형식

```markdown
## 한 줄 답
## 재현 확인      기존 README 수치(단독 조건 4개)를 먼저 재현했는가
## 결과           위 6개 항목 표·수치
## 확인 / 추정 / 미확인
## 한계
```

## 결과 전달

대화로 Claude에게 전달하면, 검토 후 `2026-08-18-strategy-candidates/README.md`에
§11(결합 견고성)로 추가하고 §9 결론(우선순위)을 필요하면 갱신한다.
