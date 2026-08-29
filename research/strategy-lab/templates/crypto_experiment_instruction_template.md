# Crypto 트랙 실험 지시서 템플릿

이 템플릿을 복사해서 실제 지시서를 만든다. `{{ }}`는 채워 넣을 자리다.
실행 전에 반드시 `research/strategy-lab/rule_discovery_criteria.json`을
읽고 그 안의 임계값으로 스스로 판정한다.

---

## 실험 대상

- 전략/이벤트: {{예: Bollinger Squeeze + Volume, funding premium, taker ratio}}
- 데이터 소스: `data/crypto/{daily,4h,basis,funding,activity}` - 새 자산/
  거래소 데이터가 필요하면 이 단계에서 멈추고 보고

## 순서 (건너뛰지 않는다)

1. **인벤토리** - 대상 자산·기간·coverage 확인
2. **전체 자산군 검증** - 소수 종목(스모크) 결과를 전체 유니버스로 일반화
   될 때까지는 KEEP 후보로 안 올린다(V3 Bollinger+RSI가 30종목 스모크에서
   Sharpe 1.20이었다가 전체 유니버스에서 -0.22로 뒤집힌 전례 재발 방지)
3. **이벤트 집중도 확인 - crypto 트랙에서는 특히 필수**: TEST 성과가 단일
   이벤트/날짜에 쏠려있지 않은지 leave-one-event-out으로 반드시 확인
   (S2 Squeeze+Volume이 TEST 성과의 191%가 단일 이벤트 하루에 쏠려
   EVENT-CONCENTRATED로 재분류된 전례 - crypto는 KR 주식보다 개별 이벤트
   쏠림이 훨씬 잦다)
4. **TRAIN에서만 threshold 탐색**, VALID/TEST는 고정값을 보고만 함
5. **`rule_discovery_criteria.json` 기준으로 자기 판정** - KR 템플릿과 동일.
   단 `concentration.max_single_year_pct` 항목은 crypto에서는 "단일
   이벤트/날짜 집중도"로 바꿔 적용한다(연 단위 분해가 crypto 히스토리
   길이엔 안 맞음 - 위 3번의 leave-one-event-out 결과를 그 자리에 넣는다).
   표준 4개(KEEP/HOLD/REJECT/UNCLASSIFIED) 중 뭘 써야 할지 애매하면
   verdict는 UNCLASSIFIED, 실제 결론은 `original_verdict`에 그대로
   전사한다 - "조건부"를 억지로 REJECT/HOLD로 매핑하지 않는다
   (RULE_DISCOVERY_CRITERIA.md 참고)
6. **finding 작성** - `findings/crypto-{{factor-slug}}-{{YYYY-MM}}.md`,
   `RULE_DISCOVERY_CRITERIA.md`의 frontmatter 형식(`track: crypto`) 그대로.
   **`conditions` 필드와, 실제로 계산한 숫자 필드(`cagr`·`sharpe`·`mdd`·
   `win_rate`·`n`·`t_stat`)를 채운다** - 조건은 한 줄 JSON 배열로(예:
   `["bb_squeeze_pctile<=10", "volume_zscore>2"]`), 수치는 스칼라로. "안 된
   부분은 빼고 된 부분만" - 계산 안 한 지표는 생략, 지어내지 않는다. 단
   REJECT/HOLD라고 계산된 나쁜 결과를 빼면 안 된다(예: event-concentrated로
   REJECT면 그 집중도 수치 자체가 근거). **단위 주의: `cagr`·`mdd`·
   `win_rate`는 퍼센트 값 그대로(1.28%면 `1.28`, `0.0128` 아님)** - pandas가
   소수로 뽑아주는 걸 그대로 옮기면 대시보드에 100배 축소돼 표시된다.
   적기 전에 숫자가 1 미만이면 100을 곱한 값인지 확인한다

## 하지 않는 것

- 실제 주문/거래소 API 연동 - 이 프로젝트는 조회·연구 전용(CLAUDE.md
  최상단 규칙), crypto도 예외 아니다
- `config/`·`lib/`·`scripts/`·`data/backfill/` 수정

## 보고

KEEP 판정만 Claude에게 요약 보고. HOLD/REJECT는 finding에만 남긴다.
