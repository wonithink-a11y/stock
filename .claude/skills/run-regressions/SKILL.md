---
name: run-regressions
description: 코드를 바꾼 뒤 로컬 회귀(scripts/test-*)를 전부 돌리고 부산물을 되돌리는 절차. "테스트 돌려줘", "회귀 확인", "깨진 거 없어?", "커밋 전에 검사", "test-guide", "pytest" 같은 말이 나오거나, lib·scripts·config·deploy 를 고친 직후 커밋하기 전에 반드시 이 스킬을 쓴다. 변경 위험과 무관하게 항상 돌린다.
---

# 회귀 실행

npm 프로젝트가 아니라 자동 발견이 없다 (절대 규칙 8). 돌리지 않으면 아무도 대신 돌려주지 않는다.
`scripts/test-*.{py,js}` 55개를 전부 돌린다 — 실측 약 8초대(2026-10-25 로컬, 전부 통과). 위험이 작아 보여도 **항상 전부** 돌린다.
최적화 대상은 불필요한 신규 회귀 작성과 독립 검증이지 기존 회귀 실행이 아니다.

## 실행 (한 번에)

```bash
export PYTHONIOENCODING=utf-8     # 먼저. 없으면 cp949 가 이모지에서 죽어 가짜 실패 3건이 난다
fail=0
for f in scripts/test-*.py scripts/test-*.js; do
  case $f in *.py) r="python $f";; *) r="node $f";; esac
  timeout 120 $r >/tmp/o.txt 2>&1 || { echo "FAIL $f"; tail -3 /tmp/o.txt; fail=$((fail+1)); }
done
echo "failures=$fail"
git status --short
```

통과 시 보고는 한 줄: "회귀 55/55 통과". 실패·경계조건·판정 변경이 있을 때만 상세히 쓴다.

## 실패했을 때

1. 가짜 실패부터 의심: `PYTHONIOENCODING` 누락, 네트워크 필요 테스트, 로컬 pyarrow(25)와 VM pyarrow(17) 차이.
2. 내가 바꾼 파일과 실패 테스트를 연결해 본다. 연결이 안 되면 `git stash` 가 아니라 `git diff` 로 범위를 좁힌다 (stash pop 맹목 사용 금지).
3. 기대값을 고쳐서 통과시키지 않는다 — 정책 임계값을 느슨하게 고치는 것은 절대 규칙 6 위반이다. 원인을 고친다.
4. 테스트가 정책을 못 박은 경우(`tests/test_paper_sleeve_policy.py` 가 nDrop=3/pct=0.8 을 pin)는 정책 변경이므로 🔴 이다. 사용자 GO 를 받는다.

## 실행 뒤 정리

- `git status --short` 에 `data/` 아래 변경이 보이면 로컬 실행 부산물이다: `git checkout -- data/` (절대 규칙 4, `data/backfill/` 는 로컬에서 커밋하지 않는다).
- 사용자의 미커밋 파일은 건드리지 않는다. 커밋은 파일 명시 add 만.

## 같이 알아 둘 것

- **strategy-lab 테스트**(`research/strategy-lab/tests/`, 58개 파일)는 `python -m pytest` 로 도는데 **오래 걸린다**(2026-10-25 시험에서 5분 초과). 전부 돌리지 말고 바꾼 모듈에 해당하는 파일만 고른다:
  `python -m pytest research/strategy-lab/tests/test_<모듈>.py -q`.
  이 디렉터리의 `ok()` 헬퍼는 예외 없이 실패만 세는데, `tests/conftest.py` 가 이를 pytest 실패로 바꿔 준다 — conftest 를 건드리지 않는다.
- 게이트 검증은 `*_FAIL_INJECTION=gate-test` 로 인수 조건을 강제 실패시킨다. 이 훅은 실패만 만들 수 있다. 새 단계에도 같은 형태로 붙인다.
- 새 검사를 추가할 때는 그 검사가 어느 범위(전이·상태·병합)에서 잴 수 있는지 먼저 정한다. 구성상 항상 참인 검사는 정보가 없다.
- 전체 명령 전문: `docs/operations/test-guide.md`.
