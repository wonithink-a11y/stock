---
track: kr
factor: memory-price-proxy-kr-stocks-pilot
date: 2026-09-13
verdict: REJECT
original_verdict: null
criteria_version: null
conditions: ["대상 = SOXL이 아니라 개별 종목 005930·000660 (data/backfill/price/a2a 기존 KR 파이프라인 시세, 읽기 전용)", "factor 소스 2개: ECOS 404Y016 플래시메모리(NAND) PPI 2005-2026 n=147, FRED PCU3344133441 반도체 PPI n=147", "진짜 DRAM 가격 계열은 무료로 확보 불가 확인(ECOS에 D램 단독 품목 없음, TrendForce 유료, VLSI Market 20개월뿐)", "availableFrom = 월말+20일(ECOS PPI 발표관례 보수적 가정)", "4 factor x 3 horizon, soxl_leadlag_common 공용 배터리(일반화: load_fwd_returns/run_battery target_prefix)", "threshold 최적화 없음"]
reason: "SOXL이 아니라 개별 메모리기업(005930·000660) 주가가 반도체 가격지표와 관련있는지 검증. ECOS NAND PPI x FRED 반도체 PPI x 2종목 = 4개 조합, 각 24개 검정(96개 총). naive Spearman에서 산발적으로 유의한 셀이 나오나(ecos->005930 3개, ecos->000660 2개) HAC 보정하면 전부 소멸하고, 반대로 HAC에서 유의한 셀(fred->005930/000660 각 2개)은 naive에서 안 나온다 - naive와 HAC가 유의하다고 짚는 셀이 4개 조합 어디서도 단 한 번도 겹치지 않는다는 게 핵심 반증이다(96개 검정 중 순수잡음 기대치 ~4.8개와 부합). 분위수 forward return은 4개 조합 전부 단조성 없음. NAND PPI 소스의 상승/하락전환 이벤트에서 방향성 있는 격차(005930 fwd6m +40.0%/+12.0%, 000660 +60.6%/+16.0%)가 관찰되나 n=5/4로 통계 검정 자체가 불가능한 크기라 신호로 채택 안 함. 판정 REJECT - 단 진짜 DRAM 가격이 아니라 NAND PPI·반도체 전체 PPI 대용치로 시험한 한계가 있다."
cagr: null
sharpe: null
mdd: null
win_rate: null
n: 147
t_stat: null
---

# DRAM/메모리 가격 대용치 → 삼성전자·SK하이닉스 주가 파일럿 (2026-09-13)

> 사용자 질문("DRAM 가격변동이 SOXL이 아니라 하이닉스·삼성전자와 관련있는지
> 확인 안 되나") — 대상을 SOXL에서 개별 KR 메모리 기업으로 바꾼 새 파일럿.
> `soxl-semiconductor-industry-fundamentals-line-closure`의 REJECT(대상=SOXL)
> 를 뒤집는 게 아니다 — 대상 자체가 다른 별도 검증.

## 1. 데이터 가용성 확인 — 진짜 DRAM 가격은 무료로 없다

- **TrendForce/DRAMeXchange**: DDR4/DDR5 spot·contract 현재가는 공개
  페이지에 있으나 historical 다운로드는 유료 회원 전용(사용자 확인).
- **VLSI Market**(market.vlsi.kr): DDR4/DDR5/NAND 고정가 계열이 있지만
  실측 확인 결과 **이력이 2025-01~2026-08(20개월)뿐**이다. 이 배터리의
  최소표본(min_n=20)에 겨우 걸치는 수준이라 통계적으로 의미 있는 검증이
  안 된다. 제3자 비공식 집계 사이트라 신뢰도도 별도 검증 안 됨 — 채택
  안 함.
- **한국은행 ECOS 404Y016**(생산자물가지수, 품목별): 실측으로 2,680개
  품목을 전수 스캔했는데 **"D램" 단독 품목 자체가 없다.** 메모리 관련은
  "플래시메모리"(30911202AA, NAND, 2005-01~2026-07, 259개월)뿐이고
  "시스템반도체"(30911203AA, 1985~)는 로직칩이라 메모리가 아니다.

**결론: DRAM 전용 무료 장기 계열은 존재하지 않는다.** 그래서 이 파일럿은
두 대용치를 썼다 — ① ECOS 플래시메모리(NAND) PPI(메모리는 맞지만 D램은
아님), ② 기존에 이미 REJECT난 FRED 반도체 PPI(PCU3344133441, DRAM도
NAND도 아닌 반도체 전체 평균 — 단 대상이 SOXL에서 개별종목으로 바뀌었으니
재사용이지 반복은 아니다).

## 2. 대상 — 기존 KR 파이프라인 시세 재사용(신규 수집 없음)

`data/backfill/price/a2a/*.jsonl.gz`에서 005930·000660 일별 종가만
읽기 전용으로 추출했다(이 스크립트는 그 경로에 아무것도 쓰지 않는다).

## 3. 결과 — 4개 조합 전부 같은 반증 패턴

| | ECOS NAND→005930 | ECOS NAND→000660 | FRED PPI→005930 | FRED PPI→000660 |
|---|---|---|---|---|
| naive 유의 셀 | 3개 | 2개 | 0개 | 0개 |
| HAC 유의 셀 | 0개 | 0개 | 2개 | 2개 |
| naive∩HAC 동시유의 | 없음 | 없음 | 없음 | 없음 |
| 분위수 단조성 | 없음 | 없음 | 없음 | 없음 |

**핵심 반증**: naive와 HAC가 유의하다고 짚는 셀이 4개 조합 어디서도 단
한 번도 겹치지 않는다. 진짜 신호라면 두 방법이 (정도 차이는 있어도)
같은 셀을 가리켜야 하는데, 매번 서로 다른 셀만 걸린다 — 96개 검정
(4조합×24) 중 순수 잡음 기대치(~4.8개)와 부합하는 수의 우연한 히트가
흩어져 있을 뿐이다.

**상승전환·하락전환 이벤트** — ECOS NAND PPI 소스에서만 방향성 있는
격차가 보인다:

```
005930: 상승전환(n=5) fwd6m +40.0%  vs  하락전환(n=4) fwd6m +12.0%
000660: 상승전환(n=5) fwd6m +60.6%  vs  하락전환(n=4) fwd6m +16.0%
```

방향은 이번엔 직관적(모멘텀형)이고 DART 파일럿의 콘트래리안 방향과도
다르다 — 파일럿마다 방향이 뒤바뀐다는 것 자체가 신뢰도를 낮춘다. 게다가
**n=4~5는 통계 검정 자체가 성립 안 되는 크기**라 특정 한두 사이클
(2016-17 낸드 슈퍼사이클 등)에 좌우됐을 가능성을 배제 못 한다 — 신호로
채택하지 않는다.

## 4. 판정 — REJECT (단, 한계를 명시)

DRAM 자체가 아니라 대용치(NAND PPI·반도체 전체 PPI)로 시험한 결과가
REJECT다. **"DRAM 가격이 메모리주와 무관하다"고 결론 내리는 게 아니라
"무료로 구할 수 있는 대용치로는 신호를 못 찾았다"**는 스코프 한정
판정이다 — 지금까지의 REJECT들과 같은 원칙.

## 5. 재개 조건

- TrendForce/DRAMeXchange 유료 접근을 실제로 고려하게 되면(별도 비용
  승인 필요, 이 파일럿과 별개 결정) 진짜 DRAM spot/contract로 재검증.
- NAND PPI 상승/하락전환 이벤트의 방향성 격차는 표본이 더 쌓이면
  (앞으로 몇 사이클 더 지나면) n이 늘어날 수 있다 — 지금은 너무 이르다.

## 6. 산출물

- `research/strategy-lab/semiconductor_cycle_memory_price_kr_stocks.py` — selftest 5/5
- `research/strategy-lab/soxl_leadlag_common.py` — `load_fwd_returns`/`run_battery(target_prefix=)`로
  일반화(SOXL 전용 → 임의 가격시리즈), 기존 SOXL 파일럿 결과는 재실행으로 불변 확인
- `research/strategy-lab/data/semiconductor-cycle/memory_price_{source}_{ticker}.parquet` — 4개
