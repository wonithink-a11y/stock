# autotrader 웹 화면 — 폰에서 보기 (쉬운 설치 안내서)

이 문서는 **컴퓨터를 잘 몰라도** 순서대로 따라 하면 되도록 썼습니다. 어려운 말이 나오면 바로 옆에 쉬운 설명을 적었습니다.
모르겠으면 **그 화면을 캡처해서 저(Claude)에게 보내주세요.** 틀려도 괜찮습니다. 실수로 망가지는 일은 거의 없습니다.

> **개정(2026-09-20)**: 저장소 기록을 찾아보니 우리 집(VM)에는 이미 **nginx(경비 아저씨) + 인증서 + 주소**가 있습니다
> (`wonithink-stock.duckdns.org`, 주식 화면이 쓰는 서비스가 그 주소로 돌고 있어요). 그래서 **새로 설치하지 않고
> 기존 경비 아저씨에게 "길 하나만 추가"** 하는 방식으로 바꿨습니다. 기존 서비스는 건드리지 않습니다.

---

## 0. 이 화면이 뭐예요?

자동매매 프로그램이 오늘 뭘 했는지, 지금 뭘 가지고 있는지를 **폰으로 보는 화면**입니다.
**보기만 할 수 있습니다.** 주문을 넣거나 멈추는 버튼은 일부러 없습니다. (화면이 뚫려도 아무 일도 못 하게 하려고요.)

### 그림으로 이해하기 (집 이야기)

| 진짜 이름 | 집 이야기 |
|---|---|
| **VM** (서버) | 항상 켜져 있는 우리 집 |
| **웹 화면 프로그램** | 집 안에서 손님에게 보여줄 안내판 |
| **nginx** | 집 앞의 **경비 아저씨** (밖에서 온 사람을 안내판까지 안전하게 안내해요) |
| **포트 80, 443** | 집의 **문** (이미 열려 있어요) |
| **wonithink-stock.duckdns.org** | 우리 집 **주소** |
| **/autotrader/** | 그 집 안에서 **안내판이 있는 방 이름** (다른 방은 그대로예요) |
| **비밀번호 + 인증앱 숫자** | 방문 열 때 필요한 **열쇠 두 개** (둘 다 맞아야 열려요) |

### 지켜주는 것 (안전장치)
- 로그인을 안 하면 **아무것도 안 보입니다.**
- 로그인해도 **처음에는 요약만** 보입니다(몇 번 했는지). **종목·금액은 안 보여요.**
- 종목·금액은 인증앱 숫자를 **한 번 더** 넣어야 5분 동안만 보입니다.
- 5번 틀리면 15분 동안 잠깁니다. 15분 동안 가만히 있으면 자동으로 로그아웃됩니다.
- 이 화면 프로그램은 **증권사 키를 읽을 수 없게** 막아 두었습니다.

---

## 1. 지금까지 확인된 것

| 항목 | 결과 | 어디서 알았나 |
|---|---|---|
| 우리 집 주소 | **`wonithink-stock.duckdns.org`** | 저장소 문서(완료-이력, 화면 코드) |
| 안쪽 문(iptables) | 열림 | 사용자 확인 |
| 바깥쪽 문(오라클) | 열림 | 사용자 확인 |
| 경비 아저씨 | 사용자는 "Caddy 있음"이라고 했지만, **저장소 기록에는 nginx** 라고 적혀 있음 | ⚠️ 아래 **확인 ⑤** 에서 확실히 합니다 |

> 왜 중요하냐면: 경비 아저씨가 nginx인데 Caddy를 또 깔면 **둘이 같은 문을 서로 지키려고 싸워서** 기존 서비스가 멈춥니다. 그래서 먼저 정확히 확인합니다.

---

## 2. 확인 ⑤ 지금 누가 문을 지키고 있나? (딱 한 번만 확인)

### VM에 들어가기
1. 윈도우 왼쪽 아래 **시작 버튼(⊞)** → `PowerShell` 입력 → **Enter**.
2. 아래를 복사해서 붙여넣고 Enter.

```powershell
ssh stock-new
```

3. 줄 맨 앞이 `ubuntu@…:~$` 로 바뀌면 **성공**입니다. (처음이면 `yes` 입력)

### 확인 명령 (VM 안에서)
```bash
sudo ss -ltnp | grep -E ':(80|443) '
```

- 나오는 글자 줄에서 **`nginx`** 가 보이면 → ✅ 정상. 이 안내서 그대로 진행하면 됩니다.
- **`caddy`** 가 보이면 → 저에게 그 결과를 알려주세요. 방식이 달라집니다. (아직 아무것도 바꾸지 마세요.)
- 아무것도 안 나오면 → 저에게 알려주세요.

### 저(Claude)에게 알려줄 것
위 명령의 **결과 글자 그대로** 붙여서 보내주세요. (비밀 정보는 안 나오는 명령이에요.)

---

## 3. 프로그램 설정하기 (코드가 올라간 뒤에 합니다)

> **VM 안에서** 합니다. 줄 맨 앞이 `ubuntu@…:~$` 일 때 한 줄씩 복사해서 붙여넣고 Enter 하세요.

**1) 최신 코드 받기**
```bash
cd ~/collector && git pull
```

**2) 설정용 폴더 만들기**
```bash
mkdir -p ~/collector-venv/autotrader/state
```

**3) 설정 파일 복사하고 저장 위치 고치기**
```bash
cp autotrader/config.example.json ~/collector-venv/autotrader/autotrader.local.json
```
```bash
sed -i 's#"state_dir": "autotrader/state"#"state_dir": "/home/ubuntu/collector-venv/autotrader/state"#' ~/collector-venv/autotrader/autotrader.local.json
```
```bash
cp autotrader/targets.example.json autotrader/targets.local.json
```

**4) 설정이 맞는지 확인**
```bash
~/collector-venv/bin/python3 -m autotrader --config ~/collector-venv/autotrader/autotrader.local.json check-config
```
`설정 OK` 라는 글자가 나오면 성공.

**5) 잔고를 한 번 읽어 보기 (주문은 안 나가요, 읽기만)**
```bash
~/collector-venv/bin/python3 -m autotrader --config ~/collector-venv/autotrader/autotrader.local.json snapshot
```
`스냅샷 저장` 이라고 나오면 성공.

**6) 비밀번호와 인증앱 만들기** ⭐ 가장 중요해요
```bash
~/collector-venv/bin/python3 -m autotrader --config ~/collector-venv/autotrader/autotrader.local.json web-setup
```
- "새 비밀번호"라고 나오면 **12글자 이상**으로 정해서 입력하세요. **입력해도 화면에 아무 글자도 안 보이는데, 정상이에요.** Enter를 누르고, 한 번 더 같은 걸 입력합니다.
- 그러면 **"키(공백 없이): ABCD…"** 라고 긴 영어·숫자가 나옵니다. **이건 지금 딱 한 번만 보여줘요.**
- 폰에서 **Google Authenticator**(구글 인증기) 앱을 설치하세요. (Microsoft Authenticator도 됩니다.)
  1. 앱을 열고 **＋** 를 누릅니다.
  2. **설정 키 입력**(직접 입력)을 고릅니다.
  3. 계정 이름은 `autotrader`, 키는 화면에 나온 글자를 **그대로** 씁니다.
  4. **시간 기준**이 선택된 걸 확인하고 추가합니다.
  5. 앱에 **6자리 숫자**가 나타나고 30초마다 바뀌면 성공이에요.

> ⚠️ 비밀번호와 이 키는 **저(Claude)에게도, 다른 누구에게도 알려주면 안 돼요.** 저는 볼 수 없게 만들어져 있습니다.

**7) 안내판 프로그램을 켜기**
```bash
sudo cp deploy/autotrader-web.service deploy/autotrader-snapshot.service deploy/autotrader-snapshot.timer /etc/systemd/system/
```
```bash
sudo systemctl daemon-reload
```
```bash
sudo systemctl enable --now autotrader-web.service autotrader-snapshot.timer
```

이렇게 켜졌는지 확인:
```bash
curl -s http://127.0.0.1:8787/autotrader/healthz
```
`ok` 라는 글자가 나오면 성공. (집 안에서 안내판이 응답한다는 뜻이에요.)

**8) 경비 아저씨(nginx)에게 "길 하나" 추가하기** ⚠️ 여기가 제일 조심할 곳이에요

기존 서비스를 건드리지 않고 **두 줄짜리 길만 추가**합니다. 실수해도 되돌릴 수 있게, 먼저 백업을 만듭니다.

8-1) 어느 파일에 주소가 적혀 있는지 찾기:
```bash
sudo grep -rl "wonithink-stock" /etc/nginx/
```
파일 이름이 한 줄 나옵니다. (예: `/etc/nginx/sites-enabled/xxxx`) 그 이름을 이 아래 `파일이름` 자리에 넣어 쓰세요.

8-2) 백업 만들기:
```bash
sudo cp 파일이름 파일이름.백업
```

8-3) 파일 열기:
```bash
sudo nano 파일이름
```

8-4) 파일 안에서 **`listen 443`** 이라고 적힌 `server {` 덩어리를 찾으세요. (`listen 80` 덩어리가 아니에요!)
그 덩어리 **맨 끝의 `}` 바로 위**에 아래 글자를 붙여넣습니다. (기존 글자는 하나도 지우지 마세요.)

```
    location = /autotrader { return 301 /autotrader/; }
    location /autotrader/ {
        proxy_pass http://127.0.0.1:8787;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 15s;
    }
```
저장: `Ctrl+O` → Enter, 나가기: `Ctrl+X`.

8-5) **검사부터 하기** (이게 통과해야 켤 수 있어요):
```bash
sudo nginx -t
```
- `syntax is ok` 와 `test is successful` 두 줄이 나오면 ✅.
- 그 외의 글자가 나오면 **켜지 말고** 화면을 캡처해서 저에게 보내주세요. (백업으로 돌리면 됩니다.)

8-6) 적용하기:
```bash
sudo systemctl reload nginx
```

> **되돌리는 방법**: 문제가 생기면 `sudo cp 파일이름.백업 파일이름` 그리고 `sudo systemctl reload nginx`. 그러면 원래대로 돌아갑니다.

---

## 4. 폰에서 확인하기 (성공 체크리스트)

폰 브라우저(크롬·사파리)에서 이 주소로 들어갑니다. **끝에 `/autotrader/` 를 꼭 붙이세요.**

```
https://wonithink-stock.duckdns.org/autotrader/
```

- [ ] 주소창에 **자물쇠 🔒** 가 보인다.
- [ ] **로그인 화면**(비밀번호, 인증앱 코드 칸)이 보인다.
- [ ] 비밀번호 + 인증앱의 **6자리 숫자**를 입력하면 **요약 화면**이 나온다.
- [ ] 요약 화면에 **종목 이름·금액이 없다**(정상!).
- [ ] 아래 "보유·주문 상세 보기"를 눌러 인증앱 숫자를 **새로** 입력하면(30초 기다려서 바뀐 숫자) 보유·잔고가 나온다.
- [ ] 5분 뒤 다시 상세를 누르면 **또 숫자를 물어본다.**
- [ ] **로그아웃** 버튼을 누르면 로그인 화면으로 돌아간다.
- [ ] (안전 확인) 원래 쓰던 주식 화면·`/accounts` 는 **똑같이 잘 된다.**

폰에 **홈 화면에 추가**(북마크)해 두면 편해요.

---

## 5. 문제가 생겼어요 (증상별 안내)

| 이렇게 보이면 | 뜻 | 이렇게 해보세요 |
|---|---|---|
| **404** 라고 나옴 | 주소 끝에 `/autotrader/` 가 빠졌거나 nginx에 길이 안 붙음 | 주소를 다시 확인. 그래도 404면 8번(nginx 추가)을 다시 |
| **502 / Bad Gateway** | 안내판 프로그램이 꺼져 있음 | VM에서 `sudo systemctl status autotrader-web` 캡처해서 저에게 |
| `nginx -t` 에서 **오류** | 붙여넣은 글자가 어긋남 | 켜지 말고 캡처해서 저에게. 백업으로 돌리면 돼요 |
| 로그인 화면에서 **"로그인할 수 없습니다"** | 비밀번호나 숫자가 틀림 (어느 쪽인지는 일부러 안 알려줘요) | 인증앱 숫자가 **바뀐 직후의 새 숫자**인지 확인. 5번 틀리면 15분 기다려야 해요 |
| **"잠시 후 다시 시도하세요"** | 잠금 | 15분 기다리세요 |
| 요약 화면의 **"스냅샷 없음"** | 잔고를 아직 못 읽음 | 3-5 (스냅샷) 다시. `~/collector-venv/logs/autotrader-snapshot.log` 캡처해서 저에게 |
| 인증앱 숫자를 **처음부터** 잃어버림 | 키를 다시 만들어야 함 | VM에서 `web-setup --reset` (3-6과 같은 방법으로 다시 등록) |
| 기존 주식 화면이 **이상해짐** | nginx 수정이 잘못됨 | **바로 백업으로 되돌리세요**(위 되돌리는 방법) 그리고 저에게 알려주세요 |
| 뭔지 모르겠음 | - | **화면을 캡처해서 보내주세요** |

## 6. 저(Claude)에게 절대 알려주면 안 되는 것

- DuckDNS **token**
- 웹 화면 **비밀번호**, 인증앱 **키(긴 영어·숫자)**, 인증앱의 **6자리 숫자**
- 증권사 **앱키·시크릿·계좌번호**
- 주소창에 `?key=` 가 들어간 주소

알려주셔도 되는 것은 **확인 명령의 결과 글자**, **화면 캡처(위 비밀이 가려진 것)**, **오류 글자**입니다.

---

## 7. 그만두고 싶을 때 (끄는 방법)

**VM 안에서** 한 줄이면 안내판이 꺼집니다. (자동매매 자체는 영향 없음)

```bash
sudo systemctl disable --now autotrader-web.service
```
nginx에 추가한 길은 남아 있어도 안내판이 꺼져 있으면 `502` 만 나올 뿐 해롭지 않습니다. 완전히 없애려면 8번의 백업으로 되돌리세요.
