# KR 트랙 실험 지시서 템플릿

이 템플릿을 복사해서 실제 지시서를 만든다. `{{ }}`는 채워 넣을 자리다.
실행 전에 반드시 `research/strategy-lab/rule_discovery_criteria.json`을
읽고 그 안의 임계값으로 스스로 판정한다 - 임계값을 지시서에 다시 베껴
적지 않는다(파일이 바뀌면 지시서가 낡은 값을 갖게 됨).

---

## 실험 대상

- factor/조합: {{예: 52주저점거리 × 외국인수급20D × PER}}
- 재사용할 기존 연구 결과: {{예: findings/flow-basic-effect-2026-08.md의
  foreign_flow_ratio - 이미 KEEP 등급, 여기서 원자료를 다시 계산하지 말고
  그 스크립트/산출물을 그대로 가져다 조건만 얹는다}}
- 데이터 소스: A2a(기술)·A4(수급)·A3b/A3c(밸류에이션) - 새 수집 필요하면
  이 단계에서 멈추고 보고(신규 데이터 소스는 Claude 판단 대상)

## 순서 (건너뛰지 않는다)

1. **인벤토리** - 각 조건 변수의 coverage·PIT 가능여부·결측률 확인. 여기서
   막히면(예: 필드 자체가 없음) 더 진행하지 말고 보고
2. **단일 조건** - 각 axis 따로 forward return 관계 확인 (IC, decile spread)
3. **2-way interaction** - 조건 2개 조합
4. **3-way / event sequence** - 필요하면
5. **TRAIN에서만 threshold 탐색**, VALID/TEST는 고정값을 보고만 함
   (60/15/25 분할 - 기존 CAND1/PBR-combined 스크립트의 분할 로직 재사용)
6. **`rule_discovery_criteria.json` 기준으로 자기 판정**:
   - t값·부호일관성·표본크기·연도집중도·(상대그룹핑 썼으면) 절대임계값
     재확인을 전부 계산해서 KEEP/HOLD/REJECT 중 하나를 스스로 매긴다
   - 애매하면 HOLD로 남긴다. 억지로 KEEP/REJECT 지어내지 않는다.
     표준 4개(KEEP/HOLD/REJECT/UNCLASSIFIED) 중 뭘 써야 할지 판단이
     안 서면 verdict는 UNCLASSIFIED로 두고, 실제로 내린 결론을
     `original_verdict`에 그대로 적는다(예: "REGIME-CONDITIONAL") -
     이 프로젝트는 "조건부"를 REJECT로도 HOLD로도 판정한 전례가 다
     있어서(RULE_DISCOVERY_CRITERIA.md 참고) 억지 매핑을 안 한다
7. **finding 작성** - `findings/kr-{{factor-slug}}-{{YYYY-MM}}.md`,
   `RULE_DISCOVERY_CRITERIA.md`의 frontmatter 형식 그대로 맨 위에 붙인다.
   **`conditions` 필드와, 실제로 계산한 숫자 필드(`cagr`·`sharpe`·`mdd`·
   `win_rate`·`n`·`t_stat`)를 채운다** - 조건은 한 줄 JSON 배열로(예:
   `["52w_low_dist<=10%", "foreign_flow_20d>0", "per<=15"]`), 숫자는 스칼라로.
   원칙은 "안 된 부분은 빼고 된 부분만" - 실제로 계산 안 한 지표는 필드
   자체를 생략한다(지어내지 않는다). 단 **REJECT/HOLD라고 계산은 했는데
   나쁜 결과라서 빼면 안 된다** - "이 조합을 썼는데 이 수치라서 실패했다"를
   보여주는 게 목적이다. `n`(표본/거래건수)과 `t_stat`은 특히 중요하다 -
   판정 게이트가 직접 이 둘을 기준으로 하므로 반드시 계산해서 채운다.
   **단위 주의: `cagr`·`mdd`·`win_rate`는 퍼센트 값 그대로(1.28%면 `1.28`,
   `0.0128` 아님)** - pandas가 소수로 뽑아주는 걸 그대로 옮기면 대시보드에
   100배 축소돼 표시된다. 적기 전에 숫자가 1 미만이면 100을 곱한 값인지
   확인한다

## 하지 않는 것

- 엔진(`strategies/*_v1/`) 백테스트 연결 - KEEP 판정 난 것만 Claude가 별도로
  진행한다(cross-sectional 통계가 실제 포트폴리오에서 사라진 전례가 이미
  여러 번 있어, 이 단계는 항상 Claude가 직접 재현)
- 노출오버레이/타이밍가치 대조군 실험 - 같은 이유로 Claude 담당
- `config/`·`lib/`·`scripts/`·`data/backfill/` 수정 - AGENTS.md §3 그대로

## 보고

**KEEP 판정이 나온 것만** Claude에게 요약 보고(finding 경로 + 핵심 수치
3~4줄). HOLD/REJECT는 finding 파일에만 남기고 별도 보고 안 해도 됨 -
다음 세션이 `findings/_registry.jsonl`로 확인한다.
