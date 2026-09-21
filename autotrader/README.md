# autotrader — 내 API 키로 돌리는 전략 교체형 자동매매 (한국투자증권)

전략을 파일 하나로 갈아끼우고, 모의투자와 실계좌를 같은 코드 경로로 돌린다. **기본은 항상 dry-run(주문 없음)** 이다.
설계 근거: `docs/control/autotrader-설계-2026-09-19.md`

> **이 프로그램은 수익을 보장하지 않는다.** 전략의 좋고 나쁨과 무관하게, 버그·API 변경·체결 차이로 손실이 날 수 있다.
> 실계좌 경로는 만든 쪽(Claude)이 실계좌로 시험하지 못했다 — 모의·가짜 브로커로만 검증됐다. **소액·낮은 한도로 시작한다.**

## 1. 빠른 시작 (모의투자)

```bash
# 1) 키는 저장소 루트 .env (gitignore) 또는 환경변수에만 넣는다 — 코드·설정 파일·커밋에 절대 넣지 않는다
KIS_VTS_APP_KEY=...        # 모의투자 앱키
KIS_VTS_APP_SECRET=...
KIS_VTS_ACCOUNT_NO=12345678-01

# 2) 설정 복사 (autotrader.local.json 은 gitignore)
cp autotrader/config.example.json autotrader/autotrader.local.json
cp autotrader/targets.example.json autotrader/targets.local.json     # 예시 전략용 목표 비중

# 3) 점검 → dry-run → (원하면) 모의 주문
python -m autotrader check-config
python -m autotrader run                 # 주문 없음, 계획·위험 검사 결과만 출력
python -m autotrader run --execute       # 모의투자 계좌에 실제 주문
```

## 2. 내 전략 만들기

`autotrader/strategies/_template.py` 를 `내전략.py` 로 복사하고 `decide(ctx)` 에서 **`Intent` 목록**을 돌려준다.
설정 파일에 `"strategy": "내전략"`, `"params": {...}` 를 적으면 끝이다.

```python
class MyStrategy(Strategy):
    name = "my_strategy"; markets = ["KR"]
    def decide(self, ctx):
        if "005930" not in ctx.positions("KR"):
            return [Intent("005930", "BUY", 1, market="KR", order_type="market", reason="예시")]
        return []
STRATEGY = MyStrategy
```

전략은 **브로커를 직접 부르지 않는다.** 주문은 엔진이 위험 검사를 거쳐 낸다 — 전략 버그가 한도를 뚫을 수 없다.
`ctx` 로 쓸 수 있는 것: `positions(market)` · `cash(market)` · `quote(symbol, market)` · `now` · `params` · `state`(실행 사이에 유지).
국내 지정가는 **호가단위**를 전략이 맞춰야 한다(안 맞으면 KIS 가 거절하고 그 실행이 중단된다). 시장가는 그런 걱정이 없다.

## 3. 안전장치 (엔진이 강제)

| 장치 | 내용 |
|---|---|
| dry-run 기본 | `--execute` 없으면 주문이 안 나간다 |
| 허용 종목 | `symbol_allowlist` 에 없는 종목은 거부, 목록이 비면 `--execute` 자체가 막힘 |
| 금액 한도 | 주문당 · 일일(원장 누적, 실행이 달라도 합산) · 실행당 주문 수 · 종목당 보유금액. 기본값이 보수적이다 |
| 가격 밴드 | 지정가가 직전 시세에서 ±5% 를 넘으면 거부(호가 착오 방지) |
| 공매도·신용 없음 | 가진 수량 이상 매도 거부, 현금 초과 매수 거부 |
| 킬 스위치 | `python -m autotrader kill` — 주문 **직전마다** 다시 확인. 해제 `resume` |
| 우리 주문만 취소 | 원장에 주문번호가 있는 것만 취소. 수동으로 낸 주문은 안 건드리고 그 종목은 건너뜀 |
| 주문 무재시도 | 주문 실패는 재시도 없이 그 실행을 중단(중복 주문 방지) |
| 시크릿 | 키는 환경변수/.env 에서만. 로그·리포트에 안 남고, 토큰·원장·상태는 `autotrader/state/`(gitignore) |

모든 실행은 `autotrader/state/runs/<시각>.json` 리포트와 `ledger.jsonl`(실행된 주문) 을 남긴다. `python -m autotrader status`.

## 4. 실전 전환 (전부 사용자가 직접) — 체크리스트

1. **모의로 충분히 돌린다.** 전략이 낸 주문, 체결, 미체결 처리를 모의에서 관찰한다.
2. KIS Open API **실전 앱키**를 발급한다. 가능하면 **주문 권한만, IP 제한 포함**. 키 이름은 시세용 `KIS_APP_KEY` 와 섞이지 않게
   `KIS_LIVE_APP_KEY` / `KIS_LIVE_APP_SECRET` / `KIS_LIVE_ACCOUNT_NO` 를 쓴다.
3. **실전 TR_ID 를 공식 예제와 대조한다.** 이 프로그램의 실전 TR_ID 는 공식 문서로 확인하지 못했다(모의 값에서 "V→T" 규칙으로 유도).
   `autotrader/kis.py` 의 `TR_IDS` 표를 KIS 공식 저장소(`koreainvestment/open-trading-api`, `examples_user/`)와 맞춰 보고,
   해외 매도의 `SLL_TYPE` 필드도 확인한다. 맞으면 설정의 `"live": {"tr_ids_reviewed": true}` 로 표시한다.
4. 설정 `"mode": "live"` 로 바꾸고 **먼저 `--execute` 없이 dry-run** — 실전 키로 잔고·시세 조회만 확인한다(읽기 전용).
5. 한도를 **아주 작게** 잡는다(`risk`). 실계좌 `--execute` 는 아래 셋이 **모두** 있어야 열린다:
   - 설정 `"live": {"enabled": true, "tr_ids_reviewed": true}`
   - 환경변수 `AUTOTRADER_ALLOW_LIVE=I-ACCEPT-REAL-TRADES` (설정 파일만 고쳐서는 못 켠다 — 서비스 환경에만 둔다)
   - 실행 인자 `--execute`
6. 며칠 관찰한 뒤 한도를 올린다. **킬 스위치 사용법을 미리 익혀 둔다.**

하나라도 빠지면 실행이 거부된다(조용히 강등하지 않는다). `python -m autotrader check-config` 가 무엇이 빠졌는지 알려 준다.

## 5. 서버(VM)에서 자동으로 돌리기

`deploy/autotrader.service` / `.timer` 는 5분마다 `run-due` 를 부른다 — **프로필(§8)의 예약 시각이 된 것만** 돈다. **dry-run 으로 배포**된다:

```bash
sudo cp deploy/autotrader.service deploy/autotrader.timer /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now autotrader.timer                 # 먼저 dry-run 으로 로그 확인(~/collector-venv/logs/autotrader.log)
sudo systemctl edit autotrader.service                       # 주문을 켜려면 ExecStart 를 비우고 run-due --execute 로,
                                                             # 실전이면 Environment=AUTOTRADER_ALLOW_LIVE=... 도 여기에만
```

`--execute` 를 붙여도 주문은 프로필 파일에 `"auto": "execute"` 인 프로필만 나간다. VM 에는 GitHub 자격증명을 두지 않는다(프로젝트 규칙) —
`state/` 는 VM 로컬이고 커밋되지 않는다. 코드 갱신은 매일 06:30 `collector-pull` 이 한다.

## 6. 한계 (정직하게)

- 실전 TR_ID·해외 매도 `SLL_TYPE`·시세 TR 은 공식 문서 대조가 안 됐다(§4-3). 조회 TR 이 틀리면 조회가 실패할 뿐이지만 **주문 TR 이 틀리면 거절되거나 다른 동작일 수 있다.**
- 해외는 나스닥(NASD)만. 국내 주문 취소는 지원하지 않는다(KRX 당일물 — 장 마감에 소멸, 남은 미체결이 있으면 그 종목은 그날 건너뜀).
- 잔고 기준 정합(브로커가 정본)이지만 부분체결·정정·호가단위·거래정지 종목 등은 전략이 다룬다.
- 선물·옵션·크립토는 이 프로그램 범위가 아니다(기존 RV20 선물 자동화는 별도 경로로 돈다).
- 예제 전략 `target_weights` 는 구조를 보여주는 예시다 — 수익성을 검증한 전략이 아니다.

## 7. 폰에서 보는 웹 화면 (읽기 전용)

VM 에서 돌리고 폰으로 본다. **보기만 가능**하다(주문·킬 스위치 버튼 없음). 설치는 `docs/control/autotrader-웹화면-설치-가이드.md`(초등학생용 순서 안내).

- `python -m autotrader snapshot` — 브로커를 읽기 전용으로 조회해 `state/snapshot.json` 갱신(5분 타이머 `autotrader-snapshot`)
- `python -m autotrader serve` — 127.0.0.1:8787 웹 서버(HTTPS·주소는 **기존 nginx** 가 `/autotrader/` 경로로 넘겨준다 — `--base-path /autotrader`, 예시 `deploy/nginx-autotrader.location.example`). **KIS 키를 못 읽는다**(유닛이 `.env` 접근 차단)
- `python -m autotrader web-setup` — 비밀번호(12자 이상)와 인증앱(TOTP) 등록. 비밀번호는 화면에 안 보이게 입력, 인증앱 키는 그때 한 번만 출력
- 노출: 로그인 전 = 로그인 폼뿐 · 로그인 후 = 요약 + 상세(보유·잔고·주문, 계좌번호는 어디에도 안 나옴). 로그인은 비밀번호 + 인증앱 한 번, 유휴 30분 로그아웃(설정 `web.idle_min`).
  더 엄격하게: `web.require_reauth_for_details: true` 면 상세를 볼 때마다 인증앱 코드를 다시 묻는다.
- **로그인 알림**: `python -m autotrader notify-logins`(유닛 `autotrader-notify`)가 로그인 기록을 읽어 텔레그램으로 알린다 — 성공 즉시, 실패는 묶어서, 시간당 상한. **토큰은 이 프로세스만** 가진다(웹 프로세스는 못 봄). `--test` 로 연결 확인.
- 잠금: 같은 IP 5번 실패 15분 · 전체 20번/시간 실패 30분 · 유휴 15분 로그아웃 · 쿠키 HttpOnly/Secure/SameSite=Strict
- 한계: 패스키(지문) 인증은 아직 없다(다음 단계). 인터넷에 열리는 주소이므로 인증 코드의 결함이 가장 큰 위험이다 —
  회귀 `scripts/test-autotrader-web.py`(52건)와 변이 테스트로 핀했지만 외부 보안 검토는 받지 않았다.

## 8. 프로필 — 키와 전략을 바꿔 끼우기

프로필 = **키 묶음 + 전략 + 한도 + 예약 시각**을 이름 하나로 묶은 JSON 파일이다. 기본 설정 파일 옆 `profiles/<이름>.json`
(VM: `~/collector-venv/autotrader/profiles/`). 여러 개를 동시에 둘 수 있고, 각자 원장·킬 스위치·토큰·전략 상태가 따로다
(`state/profiles/<이름>/`). 웹 화면에 프로필마다 카드가 한 장씩 뜬다.

```bash
python3 -m autotrader new-profile samsung --strategy target_weights --key-prefix KIS_VTS      # 파일 생성(auto=off)
python3 -m autotrader profiles                                                              # 목록·키 유무·마지막 예약 실행
python3 -m autotrader --profile samsung run                                                 # 손으로 한 번(dry-run)
python3 -m autotrader --profile samsung kill                                                # 이 프로필만 킬 스위치
```

| 키 | 뜻 |
|---|---|
| `key_prefix` | 키 묶음. `KIS_VTS2` 면 `.env` 의 `KIS_VTS2_APP_KEY` / `KIS_VTS2_APP_SECRET` / `KIS_VTS2_ACCOUNT_NO` 를 쓴다. **키를 바꾸려면 .env 에 새 이름으로 넣고 여기만 바꾼다.** 시세용 `KIS_APP_KEY` 는 고를 수 없다 |
| `strategy` · `params` | 전략 파일 이름(`strategies/<이름>.py`)과 그 설정. **전략을 바꾸려면 여기만 바꾼다** |
| `auto` | `off`(예약 실행 안 함) · `dry`(예약 시각에 주문 없이 계획만) · `execute`(예약 시각에 주문 — 타이머에도 `--execute` 가 있어야) |
| `run_at` · `days` | 예약 시각 KST 목록(`["09:10","15:00"]`) · `weekdays`(기본) 또는 `daily`. 예약 뒤 20분 안에만 돈다 |
| `mode` · `markets` · `symbol_allowlist` · `risk` · `live` | §1~§4 와 같다 |

- 같은 회차는 한 번만 돈다(성공·실패 무관, 실행 **전에** 기록 — 재시도로 중복 주문을 내지 않는다).
- 주문 접수·오류·실행 거부는 텔레그램(`TELEGRAM_CHAT_ID`)으로 요약이 온다. 깨진 프로필 파일은 하루 한 번 알린다.
- 공휴일은 모른다 — 장이 닫힌 날 국내 주문은 KIS 가 거절하고 그 회차가 오류로 끝난다(다음 회차에 영향 없음).
- 같은 계좌를 여러 프로필이 쓰면, 서로의 미체결 주문을 "남의 주문"으로 보고 그 종목을 건너뛴다(안전 쪽).

### 8-1. 무한매수법 프로필 (`strategies/infinite_buying.py`)

옛 러너(`research/strategy-lab/run_infinite_buying_daily.py --mode vts`)와 **같은 엔진·같은 계약**이다. 2026-09-22 VM 에서
같은 계좌·같은 상태로 dry-run 해 8건(TQQQ·SOXL 각 4건)의 가격·수량이 옛 러너와 완전히 같음을 확인했다.

```json
"strategy": "infinite_buying",
"params": {"rules_file": "/home/ubuntu/collector-venv/infbuy/_rules.local.json", "tickers": ["TQQQ", "SOXL"],
           "seed_usd": 50000, "splits": 40, "import_state_dir": "/home/ubuntu/collector-venv/infbuy/state"},
"markets": ["US"], "symbol_allowlist": ["TQQQ", "SOXL"], "run_at": ["21:30"],
"risk": {"US": {"max_order_value": 3000, "max_daily_value": 10000, "max_orders_per_run": 20, "price_band_pct": 30,
                "max_position_value": 60000, "allow_sell": true}}
```

- `import_state_dir` 는 옛 러너의 회차(T)를 **처음 한 번만** 이어받는다. 이후엔 프로필 상태만 쓴다.
- 한도는 기본값(주문당 $300·가격밴드 5%)으로는 전부 거부된다 — 위처럼 넓힌다(큰수 매도가 시세보다 +15% 안팎).
- **옛 러너 타이머(`infinite-buying-vts`)와 둘 다 주문을 켜지 않는다** — 같은 계좌에 같은 주문이 두 번 나간다.
  프로필로 옮기면 `sudo systemctl disable --now infinite-buying-vts.timer` 후 프로필 `auto` 를 올린다.
  (서로의 미체결은 "남의 주문"으로 보고 그 종목을 건너뛰긴 하지만, 그건 겹침을 늦게 막는 장치이지 막는 방법이 아니다.)
- 모의투자는 LOC 를 못 받아 지정가로 낸다 — 이 숫자는 전략 판정용이 아니다(판정 정본은 옛 러너 `--mode paper`).
- MOC(역전 첫날 매도)는 autotrader 에 없는 주문이라 건너뛰고 상태에 `skippedMOC` 로 남긴다 — **실전에서는 규칙과 다르다**.

## 9. 웹 화면에서 조작하기 — 모의는 바로, 실계좌는 서버가 허락한 것만

상세 화면의 "조작" 칸: 자동 끄기·dry-run·주문 켜기, 지금 실행, 킬 스위치. 웹은 **요청 파일만** 쓰고(키 없음) 주문은 `run-due` 가 낸다.
킬 켜기 말고는 매번 새 인증앱 코드가 필요하고, 모든 조작은 텔레그램으로 즉시 온다.

**실계좌 프로필을 웹에서 켜려면 서버에서 먼저 한 번**(전부 사용자가 한다):

1. 실전 키를 `.env` 에 `KIS_LIVE_APP_KEY` / `_APP_SECRET` / `_ACCOUNT_NO`(또는 원하는 접두사)로 넣는다.
2. 실전 TR_ID 를 공식 문서와 대조한다(§4-3).
3. 프로필 파일에 아래를 적는다. **한도는 작게** — 웹이 뚫렸을 때의 손실 상한이 이 값이다(웹은 한도·종목·키를 못 바꾼다).
   ```json
   "mode": "live", "key_prefix": "KIS_LIVE", "web_live_allowed": true, "auto": "off",
   "live": {"enabled": true, "tr_ids_reviewed": true},
   "risk": {"US": {"max_order_value": 300, "max_daily_value": 1000, ...}}
   ```
4. `sudo systemctl edit autotrader.service` 에 `Environment=AUTOTRADER_ALLOW_LIVE=I-ACCEPT-REAL-TRADES` 와 `run-due --execute`.

그 뒤로는 웹에서 켜고 끈다. 실계좌 **주문 켜기**와 주문 상태의 **지금 실행**에는 인증앱 코드 + 확인 문구 `실계좌주문` 이 필요하다.
끄기·킬 스위치는 문구 없이 된다. `web_live_allowed` 가 없는 실전 프로필은 웹에서 끄기만 된다.
실계좌 프로필을 연결하면 그 보유·손익이 웹 화면에 보인다(계좌번호는 안 보인다).

### 9-1. 패스키(지문) — 실계좌 주문 켜기를 피싱에서 지킨다

인증앱 코드는 가짜 로그인 화면이 받아서 그대로 중계하면 뚫린다. 패스키는 브라우저가 **주소(도메인)에 묶어** 서명하므로
가짜 사이트에서는 서명 자체가 안 나온다. 그래서 **패스키가 하나라도 등록되면 실계좌 주문 켜기·실행은 패스키로만** 된다.

- 서버 준비(한 번): `~/collector-venv/bin/pip install "webauthn>=2.2,<3"`, 기본 설정 `web` 에
  `"rp_id": "wonithink-stock.duckdns.org", "origin": "https://wonithink-stock.duckdns.org"` → `sudo systemctl restart autotrader-web`
- 등록: 폰 화면 → "🔑 패스키(지문) 관리" → 인증앱 코드 → "이 기기로 패스키 등록". 여러 기기 등록 가능. 등록은 텔레그램으로 알린다.
- 등록 코드(서버): `cd ~/collector && ~/collector-venv/bin/python3 -m autotrader --config ~/collector-venv/autotrader/autotrader.local.json passkey-enroll`
- 삭제는 **서버에서만**: 같은 명령의 끝을 `passkey-reset` 으로 (웹에서 지울 수 있으면 공격자가 지우고 코드 방식으로 되돌린다).
- 폰을 잃어버리면 서버에서 `passkey-reset` 후 새 폰으로 다시 등록한다. 로그인은 여전히 비밀번호 + 인증앱 코드다.
