# A3b 결정 브리프 — 사람이 정할 것

**이 문서는 계약 설계가 아니다.** 세 안의 비용과 효과만 나란히 놓는다. 설계를 먼저
하면 결정이 그쪽으로 기운다 — 만든 것은 버리기 어렵다.

작성 2026-08-07 (A3 collect #3 이전) · 수치 출처는 코드와 실측이며 §4에 재현 명령이 있다

---

## 0. 한 줄

**`alotMatter` 하나만 수집하면 `availableWeight`가 0.4475 → 0.68로 임계 0.6을 넘는다.
발행주식총수는 필요 없다.** 이것이 이번 브리프에서 새로 확인된 사실이다.

---

## 1. 지금 막혀 있는 것

```
availableWeight = 0.4475  <  criteria.minimumDataCoverage = 0.6
→ 운영 정책이 전 종목을 '유보'로 만든다
```

임계를 낮춰 통과시키는 길은 없다. 커버리지 미달을 점수로 덮지 않는 것이 절대 규칙 1이다.

카테고리별로 살아 있는 비율은 `fundamental 0.85 · valuation 0 · technical 1 ·
supplyDemand 0`이다. **valuation이 통째로 0인 것**이 결정적이며, 그 넷 중 셋이
EPS 하나에 걸려 있다.

---

## 2. 세 안

### 안 A — A3b 신설 (`alotMatter` 수집)

DART `alotMatter.json`(배당에 관한 사항)에서 **주당순이익 · 주당현금배당금** 두 값을
가져온다. A3가 쓰는 `fnlttSinglAcnt.json`(주요계정)에는 이 둘이 없다 — 스펙의 누락이
아니라 엔드포인트의 부재다(교훈77).

**여는 것**

| 지표 | 카테고리 | 필요한 것 |
|---|---|---|
| `shareholderReturn` | fundamental | 주당현금배당금 이력 |
| `perRelative` | valuation | EPS + 업종 횡단면(sicCode는 A3에 있다) |
| `peg` | valuation | PER ← EPS |

**열지 못하는 것** — `pbr`은 발행주식총수를 요구하고 `alotMatter`는 그것을 주지 않는다.
`marginOfSafety`는 소스 자체가 미정이다.

```
0.4475  →  0.68        alotMatter만 (valuation 0 → 0.6)
```

**비용**

```
조회 격자   (법인 × 사업연도) — A3와 같은 모양
            A3 실측: 보고서 확보 24,200 + 공백 6,471 = 30,671회
            A3b도 같은 격자이므로 같은 자릿수를 본다
일 예산     A3 몫 16,000 (전체 20,000 − 안전여유 4,000)
소요        A3 실측 4일(08-05~08-08, 3,801법인). A3b도 3~4일
```

A3가 이미 (법인, 사업연도, 접수번호) 격자를 산출물에 갖고 있으므로 A3b는 **탐색 없이
그 격자만 조회**할 수 있다. 그러면 공백 6,471회가 줄어 A3보다 짧아질 여지가 있다 —
다만 이것은 설계 선택이지 지금 확정할 것이 아니다.

### 안 B — 축소 채점 (연구용)

`valuation`을 빼고 `fundamental + technical`만으로 돌린다.

```
availableWeight 0.4475 유지 → 운영 정책상 전 종목 '유보'
```

백테스트·연구에는 쓸 수 있으나 **운영 산출은 나오지 않는다.** A5 프레임워크는
결측 전파를 정상 경로로 다루므로 코드 변경 없이 지금도 가능하다. 비용 0, 효과 0.

### 안 C — criteria 임계 완화

`minimumDataCoverage`를 0.4475 이하로 내린다.

**절대 규칙 1과 정면으로 충돌한다.** 커버리지 60% 미만이면 '유보'라는 규칙은
"정직한 점수"의 핵심이고, valuation이 0인 상태의 점수는 가치평가를 하지 않은 점수다.
비용은 0이지만 이 안을 고르면 프로젝트의 전제가 바뀐다.

---

## 3. 비교표

| | 안 A (alotMatter) | 안 B (축소 채점) | 안 C (임계 완화) |
|---|---|---|---|
| availableWeight | **0.68** ✅ | 0.4475 ❌ | 0.4475 (임계를 내림) |
| 예상 호출 | ~30,700 (격자 재사용 시 감소) | 0 | 0 |
| 예상 소요 | 3~4일 | 즉시 | 즉시 |
| 새 수집 코드 | 필요 (A3 골격 재사용 가능) | 불필요 | 불필요 |
| 운영 산출 | 나온다 | 안 나온다 | 나온다(품질 미달) |
| 절대 규칙 1 | 지킨다 | 지킨다 | **어긴다** |

참고로 그 다음 단계까지 갔을 때의 상한이다.

```
0.68   A3b(alotMatter)
0.74   + 발행주식총수 → pbr
0.94   + A4 수급 (계약 미정)
```

발행주식총수는 **0.06밖에 더 열지 않는다.** A3b와 묶어서 결정할 사안이 아니며,
0.68에서 이미 임계를 넘으므로 별도 단계로 미룰 수 있다.

---

## 4. 재현

```bash
node -e "
const {FEATURES, availableWeight}=require('./lib/a5/featureRegistry.js');
const c=require('./config/criteria/KR-2.2.json');
console.log('현재', availableWeight(c).total);
['shareholderReturn','perRelative','peg'].forEach(k=>FEATURES[k].available=true);
console.log('A3b(alotMatter)', availableWeight(c).total);
"
```

**`weightUnlockedBy(criteria, 'A3b')`를 그대로 쓰면 안 된다.** 그 함수는
`stage === 'A3b'`인 피처를 전부 켜는데 거기에 `pbr`이 들어 있다. `pbr`의 blocker는
EPS가 아니라 발행주식총수이므로 0.2925는 과대 추정이다. 레지스트리의 `stage` 필드가
A3b의 범위를 미리 가정하고 있는 셈인데, **그 범위가 바로 지금 정할 것**이라
지금은 고치지 않고 사실만 적어둔다. 안 A로 결정되면 `pbr`의 stage를 분리하는 것이
그 결정의 첫 반영이다.

---

## 5. 결정 항목

```
□ 안 A · B · C 중 하나
□ (안 A인 경우) 발행주식총수를 A3b에 포함할 것인가 — 0.06 추가, 소스 미정
□ (안 A인 경우) A3 격자 재사용 여부 — 호출량과 PIT 정합성이 함께 걸린다
```

계약 설계(입력·출력·상태·resume·quota·diagnostics·merge)는 이 결정 뒤에 시작한다.
A3 collect와 완전히 독립이므로 언제 시작하든 수집을 방해하지 않는다.

---

## 관련

- `docs/A5-1.0-입출력계약.md` §1~§2 — 무엇이 없는가의 실측, 세 안의 원 출처
- `lib/a5/featureRegistry.js` — `available` 플래그가 이 수치의 단일 출처
- `트랙A-인수인계-ClaudeCode전환.md` §9.6.1 — A5 운영 투입이 막힌 경위
