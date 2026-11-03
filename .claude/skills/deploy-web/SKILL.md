---
name: deploy-web
description: 이미 설치된 VM 서비스(주로 autotrader 웹 `autotrader-web`)의 코드만 고친 뒤 다시 배포하는 절차 — 회귀 → 커밋 → PR·병합 → VM pull → 재시작 → 확인. "웹 배포해", "화면 고친 거 올려줘", "VM 에 반영해", "autotrader 웹 다시 띄워", "배포해" 같은 말이 나오면 반드시 이 스킬을 쓴다. 새 유닛·타이머를 처음 까는 건 deploy-unit 이다.
---

# 웹(기존 유닛) 재배포

VM 은 GitHub `main` 에서 pull 한다 — **main 에 들어가지 않은 코드는 VM 에 없다.** 기존 유닛 재시작은 "바로 하는" 정형 운영이다(CLAUDE.md 실행 기준).
작업 VM 은 `ssh stock-new`(hostname 은 `stock`). 엉뚱한 기계에 붙으면 오류 없이 "파일이 없다"가 나온다.

## 1. 회귀 (항상)

```bash
export PYTHONIOENCODING=utf-8
for f in scripts/test-autotrader*.py; do python "$f" 2>&1 | tail -1; done
```
웹만 고쳤어도 전부 돌린다(1분 안쪽). 화면을 바꿨으면 데모로 폰 폭 확인: launch.json `autotrader-web-demo`(포트 8799, 쿠키 `at_sess=demo`), 375px 에서 `scrollWidth == innerWidth`.

## 2. 커밋 → PR → 병합

- 파일 명시 `git add` (`-a` 금지). 이미 병합된 브랜치에 이어 쓰지 말고 **`git checkout -B <새 브랜치> origin/main`** 에서 커밋한다 — 옛 브랜치는 병합 뒤 main 과 갈라져 있다.
- `git push -u origin <브랜치>` → `gh pr create --base main` → 사용자가 "배포해"라고 했으면 `gh pr merge <번호> --merge`(force push 금지).

## 3. VM 반영

```bash
ssh stock-new 'cd ~/collector && git pull -q --ff-only && git log --oneline -1 && sudo -n systemctl restart autotrader-web && sleep 2 && systemctl is-active autotrader-web && curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8787/autotrader/healthz'
```
- `git log` 첫 줄이 방금 병합 커밋인지 본다. `active` + `200` 이어야 한다(경로는 `/autotrader/healthz` — 접두사 없이 부르면 404).
- 타이머가 부르는 oneshot(`autotrader.service` 등)은 재시작이 필요 없다 — 다음 실행이 새 코드를 읽는다.
- 웹 유닛은 허용목록 격리(`BindReadOnlyPaths`) — **새 파일을 읽게 했으면** `deploy/autotrader-web.service` 에 추가하고 `daemon-reload` 가 필요하다(이건 사용자 sudo 몫, deploy-unit 참고).

## 4. 화면 확인 (로그인 없이 VM 안에서 그려 본다)

웹은 패스키라 Claude 가 브라우저로 못 들어간다. VM 에서 같은 코드로 메모리 세션을 만들어 렌더한다(상태 파일은 읽기만):

```bash
ssh stock-new 'cd ~/collector && ~/collector-venv/bin/python3 - <<"EOF"
from pathlib import Path
from autotrader import web, web_auth as A
from autotrader.config import load_config
cp = Path.home() / "collector-venv/autotrader/autotrader.local.json"
cfg = load_config(cp); sd = web.state_dir(cfg)
app = web.WebApp(cfg, sd, A.AuthStore(sd / "web_auth.json"), A.Sessions(), A.Lockout(), secure_cookie=False,
                 profiles=web._profile_loader(cfg, cp), quote_fetch=web._fetch_us_quote)
h = {"Cookie": f"at_sess={app.sessions.create()}"}
for path in ("/?a=paper", "/?a=live", "/strategies?a=live"):
    st, _, b = app.handle("GET", path, h, b"", "127.0.0.1")
    print(path, st, len(b))        # 여기에 확인할 문자열 검사를 붙인다
EOF'
```
- 실제 `web_auth.json` 을 넘겨야 한다(없는 경로면 503 '설정 필요'만 나온다).
- `serve()` 가 넘기는 인자(예: `quote_fetch`)를 여기서도 똑같이 넘긴다 — 빠뜨리면 그 칸이 조용히 안 보인다.

## 5. 보고·기록

한 줄: PR 번호·병합 커밋 · VM `active`/`200` · 렌더 확인한 것 · **폰 실기기 미확인**(사용자 몫). 오늘 인수인계에 2~3줄 덧붙인다.
되돌리기: `git revert <병합 커밋>` → 같은 절차로 재배포.
