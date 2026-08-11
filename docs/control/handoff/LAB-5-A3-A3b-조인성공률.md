# LAB-5 — 재무에 EPS가 실제로 붙는가

```
발행   2026-08-11 · Claude
순서   ★ 1순위 — 내일 수집이 끝나기 전에
분량   반나절
```

## 한 줄

**A3(재무)와 A3b(EPS·배당)를 조인했을 때 몇 %가 붙는지 세고, 안 붙는 것이 어디에
몰려 있는지 본다.**

## 왜 지금 이걸 하나

이 프로젝트는 종목을 4개 축으로 점수화합니다. 그중 **valuation 축**은 PER 같은 지표를
쓰고, PER은 `주가 ÷ EPS` 입니다. **EPS가 없으면 그 축이 통째로 죽습니다.**

지금 문서에는 "A3b가 들어오면 계산 가능한 비중이 0.4475 → 0.68이 되어 운영 기준
0.6을 넘는다"고 적혀 있습니다. 그런데 **그 0.68은 "A3b가 EPS를 준다"고 가정하고 계산한
값이지, 실제로 조인해 본 결과가 아닙니다.**

조인이 많이 실패하면:

```
valuation 축이 죽는 종목이 생긴다
      ↓
그 종목은 3축이 아니라 2축으로 채점된다
      ↓
선언한 모델(3축)과 달라서 백테스트 표본에서 빠진다
      ↓
0.68 이라는 숫자가 종이 위 숫자가 된다
```

**수집이 내일 끝납니다.** 구조적 문제가 있다면 지금 알아야 합니다.

## 배경 — 이것만 알면 됩니다

두 데이터셋은 **같은 회사의 같은 사업연도**를 각각 다른 공시에서 가져왔습니다.

```
A3    재무제표 본문에서    매출·영업이익·순이익·자본·부채 …
A3b   배당 관련 공시에서   주당순이익(EPS) · 주당현금배당금
```

같은 회사·같은 연도라도 **공시 시점이 다를 수 있습니다.** 그래서 조인 키가 세 개입니다.

```
corp           8자리 법인코드. ★ 이걸로 조인합니다
fiscalYear     사업연도
availableFrom  그 정보를 세상이 알 수 있게 된 날 (공시일, YYYYMMDD)
```

**`ticker`(6자리 종목코드)로 조인하지 마세요.** 종목코드는 바뀌거나 재사용되고,
비상장 법인에는 없습니다.

`availableFrom`이 세 번째 키인 이유는 **정정공시** 때문입니다. 같은 회사·같은 연도에
서로 다른 `availableFrom`이 여러 개 있는 것은 중복이 아니라 사실입니다 — 처음 낸 공시와
나중에 고친 공시입니다. 과거 시점을 재현할 때 "그날 알 수 있었던 값"을 골라야 하므로
이 날짜를 버리면 안 됩니다.

## 입력

```
data/backfill/fundamentals/a3/*.jsonl.gz        gzip JSONL 11개 (2015~2025)
  corp · ticker · fiscalYear · availableFrom · rceptNo · fsDiv · periodEnd ·
  currency · sicCode · currentAssets · currentLiab · liabilities · equity ·
  revenue · opProfit · netIncome · accountSource

data/backfill/fundamentals/_shards_a3b/shard-*.jsonl        JSONL 8개
  corp · ticker · fiscalYear · availableFrom · rceptNo · periodEnd ·
  eps · epsSource · dividendRowPresent · dividendPerShare · dividendStockKnd

data/backfill/fundamentals/_shards_a3b/_state-*.json        JSON 8개
  scanned : { corp: { "2015": "OK" | "013" | "EARLY_STOP", … } }
```

## 재현 확인 — 먼저 이 숫자를 맞추세요

```
A3b 레코드 수                        14,578
A3b 가 다룬 법인 수 (corpsDone 합)    1,944
A3 에 재무가 있는 법인 수             3,003
```

안 맞으면 파일을 다 못 읽었거나 빈 줄을 세고 있는 것입니다. **여기서 멈추고 확인하세요.**

## 작업 단계

**① 두 데이터셋을 로드하고 키를 만든다**

```
A3   키 = (corp, fiscalYear, availableFrom)
A3b  키 = (corp, fiscalYear, availableFrom)
```

**② 세 가지 기준으로 각각 조인해 본다**

```
엄격  (corp, fiscalYear, availableFrom)   세 개 다 일치
느슨  (corp, fiscalYear)                  공시일은 무시
법인  (corp)                              연도도 무시
```

셋을 다 재는 이유는 **어디서 깨지는지 보기 위해서**입니다. 엄격은 낮은데 느슨이 높으면
`availableFrom`이 두 소스에서 어긋나는 것이고, 느슨도 낮으면 EPS 자체가 없는 것입니다.
원인이 다르면 대응도 다릅니다.

**③ 안 붙은 A3 레코드를 분류한다**

각각에 대해 `_state-*.json`의 `scanned`를 보고 사유를 답니다.

```
그 (corp, fiscalYear) 가 scanned 에 "013"        → 조회했는데 공시에 없다
                                  "EARLY_STOP"   → 조회를 안 했다 (연속 결측으로 중단)
                        scanned 에 corp 자체가 없음 → 아직 수집 안 된 법인 (절반이 남았다)
```

**이 셋을 하나로 뭉치지 마세요.** "없다"와 "안 봤다"와 "아직 안 왔다"는 대응이 전부 다릅니다.

**④ 쏠림을 본다**

```
연도별      2015~2025 중 어느 해가 유독 낮은가
업종별      A3 의 sicCode 로 묶어서
법인 규모별  A3 의 equity 나 revenue 분위로 묶어서
```

**⑤ `availableFrom` 불일치를 따로 센다**

같은 `(corp, fiscalYear)`인데 두 소스의 `availableFrom`이 다른 건수와, 그 차이가 며칠인지의
분포를 냅니다. 이게 정정공시 처리가 실제로 어떤 모양인지 보여줍니다.

## 산출 형식

```markdown
## 한 줄 답
  완료분 1,944법인 기준, A3 레코드의 ○○% 에 EPS 가 붙는다

## 재현 확인
  14,578 / 1,944 / 3,003 — 맞음

## 조인율
  | 기준 | 붙음 | 안 붙음 | 비율 |
  | 엄격 (corp+연도+공시일) | | | |
  | 느슨 (corp+연도) | | | |
  | 법인 (corp) | | | |

## 안 붙은 것의 사유
  | 사유 | 건수 | 비율 |
  | 013 (공시에 없음) | | |
  | EARLY_STOP (조회 안 함) | | |
  | 미수집 법인 | | |

## 쏠림
  연도별 · 업종별 · 규모별 표

## availableFrom 불일치
  건수 · 일수 차이 분포

## 확인 / 추정 / 미확인
## 한계
```

## 하지 말 것

```
✗ 조인이 안 되는 건을 메우는 보정 규칙을 만들지 마세요
✗ "0.68 을 0.5 로 낮춰야 한다" 같은 수치 제안을 하지 마세요 — 정책 결정입니다
✗ ticker 로 조인하지 마세요
✗ 013 과 EARLY_STOP 을 합쳐 '결측' 하나로 세지 마세요
```

## 꼭 기억할 한계

```
★ 수집이 51.1% 입니다. 모든 비율은 하한이고, 남은 1,857법인이 분포를 바꿀 수 있습니다.
  "완료분 1,944법인 기준" 을 제목에 넣어 주세요

★ sicCode 는 현재 업종입니다. 2015년 레코드에도 지금 업종이 붙어 있습니다

★ A3b 는 A3 가 재무를 찾은 (회사, 연도) 조합만 조회하도록 설계됐습니다.
  그래서 "A3 에 있는데 A3b 에 없다" 는 결함일 수도 있고 아직 안 온 것일 수도 있습니다.
  ③ 단계가 그 둘을 가릅니다
```
