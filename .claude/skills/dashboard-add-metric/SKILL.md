---
name: dashboard-add-metric
description: 대시보드(홈 지표 띠·마감 리포트·텔레그램 요약)에 새 숫자·지표 칸을 추가하는 절차. "홈에 ○○ 넣어줘", "요약에 유가/금리/환율 추가", "마감 리포트에 ○○ 추가", "실시간으로 보이게", "칸 하나 더" 같은 말이 나오면 반드시 이 스킬을 쓴다. 값을 어디서 받고(마감 시 1회 vs VM 실시간) 어느 파일을 고치는지, VM 반영 단계에서 막히는 곳을 안내한다.
---

# 대시보드에 지표 추가

2026-10-26 WTI(유가) 추가에서 정리한 경로다. 한 번의 경험이라 어긋나면 고친다.

## 1. 값을 어떻게 받나 — 먼저 고른다

| 필요 | 방법 | 고치는 곳 |
|---|---|---|
| 마감 때 값 + 5일·20일 변화 | 마감 리포트 숫자 수집에 시리즈 추가 | `scripts/market-close-facts.py` 의 `KR_SERIES`/`US_SERIES` (`(Yahoo 심볼, 이름, 그룹, "around"/"regular")`). 5일·20일은 `series_row` 가 이미 `chg5dPct`·`chg20dPct` 로 낸다 |
| 지금 값(장 시간 무관) | VM 시세 서버에 주소 추가 | `scripts/kis-minute-history-api.py` — `/oil` 의 `handle_oil`(60초 캐시)을 본보기로. 공개 시세만, 키·계좌는 금지 |

실시간이어도 **마감 값은 남긴다**(5·20일 기준가, 주소가 죽었을 때 대체). 장중 전용이면 `intraday-check.js` 스냅샷에 싣는 길도 있으나 그건 장 시간에만 돈다.

## 2. 어디에 보이게 하나

- **홈 지표 띠**: `docs/index.html` 의 `todayTop()` — `series` 필터의 그룹 목록에 그룹명 추가. 폰은 3칸 배치(`.home-strip`)라 **칸 수를 3의 배수로** 맞춘다(5칸+1=6).
- **마감 리포트 화면**: `renderMarketReport` 류 안의 `tile(...)` 목록(미국은 이미 WTI 등 있음, 한국은 `grid.push` 카드 추가).
- **텔레그램 요약**: `scripts/send-telegram-report.py` 의 `short_message` + `scripts/test-send-telegram-report.py`.
- **루틴 지시문**: `docs/control/시장마감리포트-루틴지시.md` 의 '숫자' 예시 줄. 루틴이 이걸 보고 리포트 본문을 쓴다.
- 누르면 기간이 바뀌는 칸은 `data-strip-range` + `state.stripRange` 패턴(유가 칸) 재사용.

## 3. VM 반영 (실시간 주소를 추가했을 때만)

1. nginx 정본 `deploy/nginx-wonithink-stock.conf` 에 `location /이름 { ... }` 추가 — `/kr-intraday` 블록을 복사. **CORS 헤더(`Access-Control-Allow-Origin *`)는 nginx 에서만**, 서버 코드에서 또 붙이면 두 번 나가 브라우저가 무효로 본다.
2. push → `ssh stock-new 'cd ~/collector && git pull --ff-only'` (Claude 가능).
3. **`sudo` 는 Claude 가 못 한다**(자동 모드가 막는다). 사용자에게 아래를 그대로 주고 실행하게 한다(백업 포함, `nginx -t` 통과해야 reload):
   `sudo cp /etc/nginx/sites-available/wonithink-stock.conf{,.bak-이름} && sudo cp ~/collector/deploy/nginx-wonithink-stock.conf /etc/nginx/sites-available/wonithink-stock.conf && sudo nginx -t && sudo systemctl reload nginx && sudo systemctl restart kis-minute-history-api`
   (복사 전 `diff` 로 새 블록만 다른지 확인해 두면 안전하다.)
4. 확인: `curl -s https://wonithink-stock.duckdns.org/이름` 이 값을 주고 `-I` 에 `Access-Control-Allow-Origin` 이 **한 번**만 있는가. 서비스명은 새로 만들지 않고 `kis-minute-history-api` 를 재사용.

## 4. 확인 순서

1. 문법: `docs/index.html` 의 가장 큰 `<script>` 를 임시 파일로 빼 `node --check` (끝나면 삭제).
2. 기존 회귀(`run-regressions` 스킬) — 텔레그램 테스트 포함.
3. 폰 폭 확인은 `dashboard-phone-check` 스킬.
4. 커밋은 파일 명시 `git add`(절대 `-a` 금지) → push. 거절(`cannot lock ref`)이면 `git pull --rebase --autostash` 후 다시 push.

## 5. 사용자에게 말할 함정

- **과거 리포트에는 새 값이 없다.** 홈 띠는 최신 한국장 마감 리포트의 facts 를 읽으므로, 새 시리즈 칸은 **다음 마감 리포트(평일 18:10 KST)가 나와야** 뜬다. "적용됐나"를 물으면 이걸 먼저 말한다.
- 마감 리포트는 Actions 지연으로 몇 분~수십 분 늦을 수 있다. 시각을 앞당기자는 제안은 설계 문서(`시장마감리포트-설계-2026-10-13.md`)의 이유(마감 뒤 공시·확정 수급) 때문에 기본은 18:10 유지.
- 값이 Yahoo 10~15분 지연 시세라는 점, 투자 판단 근거가 아니라 맥락 표시라는 점(절대 규칙 1).
