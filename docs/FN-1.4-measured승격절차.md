# FN-1.4 — measured 승격 절차

**이 문서는 수치를 담지 않는다.** 임계값은 A3 finalize가 낸 전수 measured를 보고
정한다. 여기 고정하는 것은 **그 값을 어떻게 유도하고 누가 승인하는가**뿐이다.

작성 2026-08-07 (collect #3 이전) · 대상 정책 `config/policies/fundamentals.v1.json`

---

## 0. 왜 수치를 지금 쓰지 않는가

두 가지 이유가 있고 방향이 서로 다르다.

**표본이 아직 전수가 아니다.** 2026-08-07 기준 3,672/3,801법인(96.6%)이다. 남은
129는 임의 표본이 아니라 샤드 6의 꼬리이며, 폐지법인·특수공시가 몰려 있으면 분포가
움직인다. `analyze-fundamentals-a3.py`가 출력 첫머리에 이 경고를 직접 낸다.

**본 뒤에 그으면 반드시 통과한다.** 실측을 먼저 보고 임계를 정하면 그 임계는
정의상 현재 데이터를 통과한다. 교훈45가 말하는 "새로 잡는 실패 모드가 없는 임계"가
정확히 그렇게 만들어진다. 그래서 **도출식을 먼저 못 박고 값을 나중에 넣는다** —
순서가 반대면 절차가 있어도 사후 적합을 막지 못한다.

---

## 1. 절차

```
1  measured 산출      finalize가 전수에서 계산 → _quality.json · manifest
2  diff               직전 measured와 대조. 첫 승격은 probed(표본 32법인)가 비교 대상
3  후보 임계 유도      §2의 도출식으로 계산한다. 눈대중으로 맞추지 않는다
4  실패 모드 진술      후보마다 "이 선이 잡는 것"을 한 문장으로 쓴다. 못 쓰면 그 임계는 버린다
5  사람 승인          값과 진술을 함께 본다. 승인 없이 진행하지 않는다
6  정책 반영          새 버전 파일(FN-1.4). 기존 파일을 고치지 않는다
7  재실행 판정         §4
```

**3~4가 이 절차의 전부다.** 나머지는 이미 기계가 강제한다 — `test-policies.js`가
`measured` 블록의 존재로 WARN→FAIL 승격을 가르고, 정책 파일 해시가 manifest에 남는다.
승격 기계는 이미 있고 규칙만 없었다.

---

## 2. 도출식

임계는 measured에서 **한 가지 방식으로만** 유도한다. 지표마다 무엇을 재는지가
다르므로 식도 갈린다.

### 2.1 이분적 지표 — 빈 구간에 긋는다

무너질 때 서서히가 아니라 통째로 무너지는 것들이다. measured가 1.0 근처이고
실패 시 0 근처로 떨어지므로, **그 사이 아무도 살지 않는 구간**에 선을 둔다.

```
임계 = measured와 0 사이의 빈 구간. measured에서 유도하지 않는다.
```

`periodEndParsedRate`가 이미 이 형태다(0.99, 실측 전인데도 FAIL). 정찰이 주요계정
240/240 대 전체재무제표 0/240으로 갈렸기 때문에 그을 수 있었다. 이 부류에 measured를
반영해 임계를 올리는 것은 **하지 않는다** — 값이 이미 최대인데 선을 그 밑에 바짝
붙이면 잡는 것은 늘지 않고 정상 변동에만 걸린다.

해당: `periodEndParsedRate` · `futureReferenceCount`(0 고정) · 중복 키 · 형식 검사

### 2.2 등급형 지표 — measured에서 아래로 유도한다

서서히 나빠지는 것들이다. 선을 measured보다 아래에 두되 **얼마나 아래인가에 근거가
있어야 한다.**

```
FAIL 임계 = floor(measured × (1 − 허용낙폭), 소수 2자리)
WARN 임계 = 기존 값 유지 (하류 계약이 이미 그 수를 쓰고 있으면 건드리지 않는다)
```

허용낙폭은 지표별로 승인 단계에서 정하되 **근거를 함께 적는다.** 근거는 셋 중 하나다.

- 소스의 알려진 변동 폭 (예: 연도별 공시 지연의 정상 분산)
- 하류가 견디는 한계 (예: `coverageRateMin` 0.60은 절대 규칙 1의 '유보' 경계와 같은 수)
- 그 아래면 원인이 품질 저하가 아니라 구조 변화라고 말할 수 있는 지점

세 근거 중 어느 것도 못 대면 그 지표는 WARN으로 남긴다.

해당: `coverageRateMin` · `yearCoverageDrop` · 계정별 매칭률

### 2.3 임계로 만들지 않는 것 — 구성 사실

**분포는 품질이 아니다.** 다음은 measured에 기록하되 게이트를 걸지 않는다.

| 지표 | 왜 게이트가 아닌가 |
|---|---|
| `fsDiv` OFS 비율 | "연결이 없는 회사"의 비율이다. 지주·단일법인 구성이 바뀌면 움직인다 |
| 통화 분포 | 해외 소재 법인 수의 함수다 |
| 시장별 비율 | 상장·폐지의 결과다 |
| 공시 지연 분위수 | 정정공시가 섞인다. 제거 대상이 아니라 보고 대상이다 |

이것들에 임계를 걸면 **업종·시장 구성 변화가 데이터 품질 실패로 둔갑한다** —
교훈48(금융업에 유동자산이 없는 것을 결측으로 셌던 것)과 같은 모양의 오류다.
분모가 무엇인지 먼저 정하고, 분모가 회사 구성이면 게이트가 아니다.

---

## 3. 승인 단계에 제출하는 표

`measured` 블록 옆에 이 표를 함께 낸다. 값만으로는 승인할 수 없다.

```
지표 | probed | measured | 후보 임계 | 도출식(§2.x) | 이 선이 잡는 것
```

**「이 선이 잡는 것」이 비어 있으면 승인하지 않는다.** 상류 게이트가 이미 막는 것을
되풀이하는 임계는 통과율만 떨어뜨리고 새로 잡는 실패 모드가 없다(교훈45).

정책 파일의 키 이름은 `probed`다(`probeSample`이 아니다). 이름을 다르게 둔 이유는
`test-policies.js`가 **`measured`의 존재 여부로** WARN→FAIL 승격을 가르기 때문이고,
같은 검사가 `probed`에 `measured` 키가 없는 것도 함께 강제한다 — 표본으로 잰 값이
전수의 게이트 기준선이 되는 경로를 막는다.

### ★ 3.1 도출식이 없는 지표는 승격하지 않는다

§2.2의 식은 **'높을수록 좋은' 지표만** 상정한다.

```
FAIL 임계 = floor(measured × (1 − 허용낙폭), 소수 2자리)
```

`yearCoverageDrop` · `roeAbsOutlierRate` · `negativeEquityRate`는 낮을수록 좋아 이 식이
그대로 적용되지 않는다. 거울식을 **승인 단계에서 즉석으로 만들지 않는다** — §0이 막으려는
것이 정확히 그것이다. 데이터를 본 뒤에 만든 식은 그 데이터를 통과하도록 만들어진다.
식이 없으면 §2.2 마지막 문장대로 **WARN으로 남긴다.**

거울식이 필요해지면 그때 이 문서를 먼저 고치고, 다음 measured로 적용한다.

---

## 4. 승격 후 재실행 판정

CLAUDE.md의 규칙을 그대로 따른다 — **그 단계가 읽는 키가 바뀌었을 때만** 재실행한다.

FN-1.4는 `acceptance` 임계만 바꾼다. `collectionContract.fields`에 임계는 없으므로
(그 이유는 정책 파일의 `principleNote`에 있다) **A3 재수집은 하지 않는다.** finalize만
다시 돌려 새 임계로 판정한다.

`quota`도 `collectionContract.fields`에 없다. 예산 8등분 수정을 FN-1.4에 함께 넣기로
한 판단(§9)이 resume을 깨지 않는 근거가 이것이다.

---

---

## 5. 실행 기록 — 2026-08-10

절차대로 승격했다. **값과 근거는 정책 파일의 `promotion` 블록이 단일 출처다** — 여기
복사하지 않는다(복사하면 두 곳이 갈린다).

```
승격    coverageRateMin 0.86            §2.2 · floor(0.9604 × (1−0.10), 2)
        currentListedCoverageMin 0.96   §2.2 · floor(0.9942 × (1−0.03), 2) · 신설
유지    periodEndParsedRateMin 0.99     §2.1 — measured 1.0 이지만 올리지 않는다
        coverageRateMinWarn 0.60        하류 한계(절대 규칙 1)라 measured로 안 건드린다
WARN    yearCoverageDrop · roeAbsOutlierRate · negativeEquityRate    §3.1 — 도출식 없음
게이트 아님  minCorpsWithData(개수) · delistedCoverage                §2.3 — 분모가 회사 구성
```

`currentListedCoverageMin`을 신설한 이유가 §2.3의 실제 적용이다. 전체 `coverageRate`
하나만 두면 **폐지 그룹의 구성 변화가 현재 상장분의 열화를 가린다** — 실측이 현재 상장
0.9942 대 폐지 0.3592로 갈렸고, 폐지 쪽 분모에는 SPAC과 2015 이전 폐지가 섞여 있다
(`probed.delistedCoverageNote`가 예고한 그대로다).

`quota.shardBudgetMode`를 `equalSplit` → `activeShards`로 함께 바꿨다. 임계가 아니라
로직이라 §3 표 밖이며, 근거와 안전 불변식은 정책의 `shardBudgetModeNote`에 있다.
`quota`는 `collectionContract.fields`에 없으므로 §4대로 **재수집은 하지 않는다.**

---

## 관련

- `config/policies/fundamentals.v1.json` — `promotion` · `measured` · `acceptanceNote` · `probed.note`
- `scripts/test-policies.js` — measured 존재로 WARN→FAIL 승격을 강제하는 자리
- `scripts/analyze-fundamentals-a3.py` · `generate-quality-report.py` — measured의 산출 경로
- `트랙A-인수인계-ClaudeCode전환.md` §9 — 진행 상태의 단일 출처
