# LAB-6 — 무배당 44%의 분포

```
발행    2026-08-11 · Claude
Owner   AI-Lab
우선    4순위 — 급하지 않다
형식    docs/AI협업-업무분담.md §3
```

## 목적

`shareholderReturn`(fundamental 축 내 가중 0.15)이 이 분포 위에서 작동한다.
A3b가 열어 주는 지표이고, 그 축의 커버리지를 실제로 결정한다.

## 현재 상태 — 실측

```
레코드                    14,578건 (완료분 51.1%)
dividendRowPresent true   14,578건   ← 전부. '행이 없음'은 0건이다
dividendPerShare == 0      6,448건   44.2%
```

**★ '행이 없음'과 '행은 있는데 0'은 다르다**(교훈75). 지금 데이터는 **전부 후자**다.
즉 `alotMatter`가 배당 항목 자체는 항상 주고, 무배당이면 0을 준다. `shareholderReturn`
계산에서 이 둘을 같게 다루면 '모르는 것'과 '배당을 안 했다'가 섞인다.

## 입력

```
data/backfill/fundamentals/_shards_a3b/shard-*.jsonl
  필드  corp · fiscalYear · dividendPerShare · dividendStockKnd · dividendRowPresent · eps

업종 조인
data/backfill/fundamentals/a3/*.jsonl.gz     corp · fiscalYear · sicCode · netIncome · equity
```

## 기대 출력

```
1  연도별 무배당 비율        2015~2025
2  업종(sicCode)별 무배당 비율
3  dividendStockKnd 값의 분포
   → 보통주 외(우선주 등)가 섞이는가. 섞이면 어느 값이 얼마나
4  무배당 법인의 지속성
   한 번도 배당하지 않은 법인 · 중단한 법인 · 시작한 법인의 분포
5  eps 와의 관계 — 적자(eps < 0) 법인의 무배당 비율
```

3번을 놓치지 않는다. 운영 수집기는 `stock_knd`가 `'보통주'`인 행을 고른다
(`A5-1.0` §1.1). 그 필터를 통과한 뒤에도 `dividendStockKnd`에 무엇이 남는지가 이 항목이다.
`'-'` 같은 값이 섞이면 그 행이 보통주인지 아닌지를 다시 봐야 한다.

## 제약

```
shareholderReturn 의 임계나 가중치를 제안하지 않는다 — criteria 는 동결이고(규칙 5)
가중치 변경은 새 버전 승격이다
'배당을 안 한 것은 나쁘다'로 해석하지 않는다. 성장 단계 기업의 정상 선택이다
분포만 낸다
```

## 관련 계약

```
docs/A3b-1.0-배당EPS계약.md
docs/A5-1.0-입출력계약.md   §1.1 (alotMatter · stock_knd 보통주 필터) ·
                            §1.3 shareholderReturn 가중 0.15
config/criteria/KR-2.2.json  동결. 읽기만 한다
```

## 관련 commit

```
02f183d   A3b collect #1 진행 회수
```

## 검증 방법

```
무배당 건수가 6,448 과 일치하는지 대조한다
같은 입력으로 재현 가능해야 한다
```

## 주의사항

```
★ 51% 시점이다. 배당은 경기 국면을 타므로 연도별 비교 시 표본 구성 변화를 함께 본다 —
  2015년 표본과 2024년 표본은 같은 법인 집합이 아니다

★ sicCode 는 PIT 가 아니다(A5-1.0 §3.3). 업종별 집계에 한계를 명시한다

★ 조회하지 않은 셀은 이 분모에 없다. scanned 의 013 · EARLY_STOP 은 레코드가
  아예 없으므로 '무배당'이 아니다. 분모를 레코드 14,578 로 고정한다
```

## 산출물

`docs/verification/`. `data/backfill/**/manifest/` 에 쓰지 않는다.
