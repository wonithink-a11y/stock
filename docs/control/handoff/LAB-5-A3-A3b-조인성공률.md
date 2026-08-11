# LAB-5 — A3 ↔ A3b 조인 성공률

```
발행    2026-08-11 · Claude
Owner   AI-Lab
우선    ★ 1순위 — A3b finalize 전에 알아야 대응할 수 있다
형식    docs/AI협업-업무분담.md §3
```

## 목적

**게이트 3의 전제를 검사한다.**

`A5-1.0` §5의 운영 게이트 3은 `availableWeight >= 0.6`이고, A3b가 들어오면
`0.4475 → 0.68`이 된다고 적혀 있다. 그런데 그 값은 `lib/a5/featureRegistry.js`의
`available` 플래그를 true로 바꿔 계산한 것이지 **실제 조인 결과가 아니다.**

EPS가 실제로 붙지 않으면 `perRelative`·`peg`가 null이 되고, 그러면 valuation 축이
죽어 그 종목의 basis가 `KR_3AXIS` 선언과 어긋난다(SB-1.0 → `BASIS_MISMATCH`로 표본에서
빠진다). **0.68은 그 일이 없다고 가정한 숫자다.**

## 현재 상태

```
A3b collect  51.1% (1,944 / 3,801법인) · 레코드 14,578 · commit 02f183d
A3           finalize 완료 (2026-08-08, d605297) · 재무 보유 법인 3,003
```

## 입력

```
data/backfill/fundamentals/a3/*.jsonl.gz        11개 (2015~2025)
  필드  corp · ticker · fiscalYear · availableFrom · rceptNo · fsDiv · periodEnd ·
        currency · sicCode · currentAssets · currentLiab · liabilities · equity ·
        revenue · opProfit · netIncome · accountSource

data/backfill/fundamentals/_shards_a3b/shard-*.jsonl    8개
  필드  corp · ticker · fiscalYear · availableFrom · rceptNo · periodEnd ·
        eps · epsSource · dividendRowPresent · dividendPerShare · dividendStockKnd
```

**조인 키는 `(corp, fiscalYear, availableFrom)`** 이다 — `A5-1.0` §3.1.
`ticker`로 조인하지 않는다. 재무 조인은 반드시 `corp_code`로 한다(CLAUDE.md 식별자 계약).

## 기대 출력

```
1  A3 레코드 중 EPS 가 붙는 비율            (완료분 기준)
2  안 붙는 레코드의 사유 분포               연도 · sicCode 업종 · 법인 유형
3  availableFrom 이 두 소스에서 어긋나는 건수
   → 같은 (corp, fiscalYear) 인데 availableFrom 이 다른 경우.
     정정공시 처리의 실제 모양이며, PIT 선택 규칙이 이 위에서 돈다
4  조인 실패가 특정 업종·연도에 쏠리는가
```

3번을 강조한다. `A5-1.0` §3.1은 *"같은 `(corp, fiscalYear)`에 서로 다른 `availableFrom`이
여럿 있는 것은 중복이 아니라 사실"* 이라고 적었다. 두 소스의 `availableFrom`이 어긋나면
**같은 사업연도의 재무와 EPS가 서로 다른 시점의 공시에서 온다.** 그 조합이 얼마나
되는지가 이 항목이다.

## 제약

```
결과를 config/policies/ · config/criteria/ · lib/a5/featureRegistry.js 에 반영하지 않는다
availableWeight 수치를 고쳐 제안하지 않는다 — 그것은 정책 결정(🔴)이다
조인 실패를 메우는 보정 규칙을 만들지 않는다
```

## 관련 계약

```
docs/A5-1.0-입출력계약.md      §3.1 PIT 선택 규칙 · §5 게이트 3
docs/A3b-1.0-배당EPS계약.md
config/policies/scoreBasis.v1.json  (SB-1.0) — basis 가 어긋나면 표본에서 빠진다
```

## 관련 commit

```
02f183d   A3b collect #1 진행 회수 (1,944법인)
d605297   A3 재무(PIT) 백필
b7a4c33   A5 게이트4 · SB-1.0
```

해시가 현재 main에 있는지 `git branch --contains <hash>`로 확인한다(업무분담 §4.2).

## 검증 방법

```
같은 두 입력으로 재현 가능해야 한다
조인 결과의 행 수 합이 A3 레코드 수와 정합하는지 대조한다
  (붙은 것 + 안 붙은 것 = 전체)
```

## 주의사항

```
★ 51% 시점이라 이 값은 하한이다. 남은 1,857법인이 분포를 바꿀 수 있다.
  "조인율 X%" 가 아니라 "완료분 1,944법인 기준 X%" 로 적는다

★ sicCode 는 PIT 가 아니다. '현재 업종'이라 전 사업연도에 같은 값이 붙는다
  (A5-1.0 §3.3). 업종별 집계에 그 한계를 명시한다

★ A3b 는 A3 의 격자를 재사용한다(a3ReuseAndScanMissing). 그래서 A3 가 보고서를
  찾은 (corp, fiscalYear) 24,750셀만 조회되고, A3 에 없는 법인은 별도 스캔이다.
  '조인 실패'와 '애초에 조회 대상이 아니었다'를 구분한다 —
  _shards_a3b/_state-*.json 의 scanned 가 그 경계를 갖고 있다
```

## 산출물

`docs/verification/` 에 둔다. **디렉터리가 아직 없다** — 이 작업이 첫 산출이면 여기서
만든다. `data/backfill/**/manifest/` 에는 쓰지 않는다(업무분담 §2).
