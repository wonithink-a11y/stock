---
name: dashboard-phone-check
description: docs/index.html(대시보드)을 고친 뒤 폰 폭(375px)에서 렌더링·동작을 확인하고 정리하는 절차. "폰에서 확인", "모바일에서 봐줘", "화면 잘 나오는지", "대시보드 고쳤어", "히트맵/탭 수정" 같은 말이 나오거나 docs/index.html 의 화면 코드를 바꾼 직후, 커밋 전에 반드시 이 스킬을 쓴다. 사용자는 폰으로 보는 일이 많아 가로 스크롤·글자 잘림이 가장 흔한 실패다.
---

# 대시보드 폰 폭 확인

`docs/index.html` 은 116KB+ 단일 파일이다 — **전체를 읽지 않는다**(절대 규칙 7). `grep -n` 으로 함수 위치를 찾고 `Read` 의 offset/limit 로 그 구간만 본다. 빌드·타입체크가 없어 문법 오류는 런타임에야 드러난다.

## 1. 정적 확인 (항상, 몇 초)

```bash
python - <<'PY'
import re
h=open('docs/index.html',encoding='utf-8').read()
open('<스크래치패드>/idx.js','w',encoding='utf-8').write(max(re.findall(r'<script[^>]*>(.*?)</script>',h,re.S),key=len))
PY
node --check <스크래치패드>/idx.js && echo JS_OK
```

수정은 가능하면 `Edit`. 한글·이모지가 섞인 큰 치환은 **스크립트를 Write 로 UTF-8 파일**로 만들고 `rep(old,new)` 마다 `count==1` 을 assert 한다(heredoc 은 cp949 로 한글이 깨진다). 파일은 바이트로 읽고 써서 줄바꿈(LF/CRLF)을 보존한다.

## 2. 폰 폭 미리보기

1. 데이터가 로컬에 없는 화면(VM 데이터·키가 필요한 탭)은 가짜 데이터가 필요하다. `docs/data/_x_test.json` 임시 사본을 두고 브라우저에서 `window.fetch` 를 가로채 그 파일을 주면 된다(종목 리포트 `/rr` 가 그 예). **끝나면 임시 파일을 지운다.**
2. `mcp__Claude_Browser__preview_start {name:"stock-dashboard"}`(포트 8733, `.claude/launch.json`) → `resize_window {preset:"mobile"}` → `navigate http://localhost:8733/`.
3. `javascript_tool` 로 탭을 직접 연다: `state.tab='<탭키>'; render();` (예: `rr`, `opinions`, `sector`). 불러오는 데이터가 있으면 1~2초 기다린다.
4. **자동 점검 숫자** — 화면을 보기 전에 숫자로 먼저:
   - 가로 스크롤: `const w=document.querySelector('.table-wrap'); w.scrollWidth===w.clientWidth` (다르면 폭 초과).
   - 개수: 카드·행·타일이 기대한 수인지(`querySelectorAll`).
   - 라벨: 히트맵이면 `.hm-s` 중 `innerText` 가 있는 칸 수(전체 화면 352개 중 8개만 이름이 나왔던 것이 문제의 출발).
5. 상호작용은 실제 `click()`/`dispatchEvent(new Event('change',{bubbles:true}))` 로 돌려 상태가 바뀌는지 본다(탭·필터·달력·두 번 탭).
6. `computer {action:"screenshot", scale:0.6}` 로 한 장 — 눈으로 잘림·겹침·색을 본다. 스크롤 위치가 어긋나면 `window.scrollTo(0, el.getBoundingClientRect().top+scrollY-10)`.
7. **마지막에 반드시**: `resize_window {preset:"desktop"}`, `preview_stop`, 임시 파일 삭제.

## 3. 커밋 전

- `run-regressions` 스킬(전체 7.8초). `docs/data/` 가 로컬 실행으로 바뀌었으면 `git checkout -- docs/data/<파일>` — `docs/data/` 의 writer 는 GitHub Actions 이다(절대 규칙 4 정신). 특히 `sector-strength.json` 은 daily-analysis(평일 16:40 KST)가 쓴다.
- 파일 명시 `git add docs/index.html …`(`git commit -a` 금지) → 커밋 → `git pull --rebase` → push → GitHub Pages 배포는 1~2분.
- 사용자에게는 "폰 폭 미리보기로만 봤다"를 숨기지 말고, 실기기 확인은 미확인으로 적는다.

## 자주 나오는 실패

- 표 가로 스크롤: `td{white-space:nowrap}` 가 기본이다. 열을 줄이거나(의견·증권사를 한 칸에), 폰에서 안 필요한 열은 `.m-hide`, 긴 줄은 칸 안에서 두 줄로.
- 호버 정보(`title=`)는 폰에서 안 보인다 — 필요한 정보는 탭 시 보이는 정보 막대나 칩 텍스트로.
- 같은 함수를 홈과 다른 탭이 함께 쓴다(예: `marketHeatmap`) — 한 곳을 고치면 둘 다 바뀐다. 양쪽을 본다.
- 새 상태를 `state`(또는 `op`·`rr` 같은 모듈 상태)에 넣을 땐 기본값을 같이 적는다. 클릭 핸들러는 `document.addEventListener('click')` 로 위임되어 있다 — 기존 `data-chart` 같은 위임 핸들러가 먼저 가로채지 않는지(속성 이름을 새로 지을 것).
