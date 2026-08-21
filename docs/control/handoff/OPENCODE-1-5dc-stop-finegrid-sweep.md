# OPENCODE-1 — 5DC-v1A-P 리스크 계약 스톱 배수 정밀 스윕 실행

너는 Codex가 아니다. 이 메시지 자체가 실행 지시서다 — 되묻지 말고 그대로 실행해라.

## 할 일 (딱 이것만)

1. 저장소 루트(`C:\Users\User\projects\stock`)에서 아래 명령 하나를 그대로 실행한다:

```bash
cd research/strategy-lab && python probe_stop_distance_finegrid_5dc.py
```

2. 이 명령의 **전체 stdout**(각 후보의 JSON 결과 3개 + 마지막 `saved:` 줄)를 그대로 대화로 붙여넣어 보고한다. 요약하지 말고 원문 그대로.
3. 실행이 끝나면(수 분 정도 걸릴 수 있다) `research/strategy-lab/reports/2026-08-21-risk-contract-fix-candidates/stop_distance_finegrid_5dc.json` 파일이 생겼는지 `ls`로 확인하고 있으면 있다고 말한다.

## 하지 말 것

- 이 스크립트나 다른 어떤 파일도 수정하지 마라. 코드 변경 없음.
- `git add`/`git commit`/`git push` 아무것도 하지 마라. 결과는 대화로만 전달한다.
- 어느 배수가 좋은지, 채택해야 하는지 판단하지 마라 — 그건 이 과제 범위 밖이다. 숫자만 보고한다.
- 스크립트가 에러를 내면 고치려 하지 말고 에러 메시지 그대로 보고하고 멈춘다.
- 이 지시서 파일 자체도 수정하지 마라.
