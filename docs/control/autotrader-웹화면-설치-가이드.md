# autotrader 웹 화면 — 폰에서 보기 (쉬운 설치 안내서)

이 문서는 **컴퓨터를 잘 몰라도** 순서대로 따라 하면 되도록 썼습니다. 어려운 말이 나오면 바로 옆에 쉬운 설명을 적었습니다.
모르겠으면 **그 화면을 캡처해서 저(Claude)에게 보내주세요.** 틀려도 괜찮습니다. 실수로 망가지는 일은 거의 없습니다.

---

## 0. 이 화면이 뭐예요?

자동매매 프로그램이 오늘 뭘 했는지, 지금 뭘 가지고 있는지를 **폰으로 보는 화면**입니다.
**보기만 할 수 있습니다.** 주문을 넣거나 멈추는 버튼은 일부러 없습니다. (화면이 뚫려도 아무 일도 못 하게 하려고요.)

### 그림으로 이해하기 (집 이야기)

| 진짜 이름 | 집 이야기 |
|---|---|
| **VM** (서버) | 항상 켜져 있는 우리 집 |
| **웹 화면 프로그램** | 집 안에서 손님에게 보여줄 안내판 |
| **Caddy** | 집 앞의 **경비 아저씨** (밖에서 온 사람을 안전한 통로로 안내해 줘요) |
| **포트 80, 443** | 집의 **문** (문이 닫혀 있으면 아무도 못 들어와요) |
| **DuckDNS 주소** | 우리 집 **주소** (예: `우리집.duckdns.org`) |
| **비밀번호 + 인증앱 숫자** | 문 열 때 필요한 **열쇠 두 개** (둘 다 맞아야 열려요) |

### 지켜주는 것 (안전장치)
- 로그인을 안 하면 **아무것도 안 보입니다.**
- 로그인해도 **처음에는 요약만** 보입니다(몇 번 했는지). **종목·금액은 안 보여요.**
- 종목·금액은 인증앱 숫자를 **한 번 더** 넣어야 5분 동안만 보입니다.
- 5번 틀리면 15분 동안 잠깁니다. 15분 동안 가만히 있으면 자동으로 로그아웃됩니다.
- 이 화면 프로그램은 **증권사 키를 읽을 수 없게** 막아 두었습니다.

---

## 1. 먼저 확인할 것 (3가지)

> 여기서는 **보기만** 하고 아무것도 바꾸지 않습니다.

### 확인 ① 우리 집 주소(DuckDNS 도메인 이름) 알아내기

1. 인터넷 주소창에 `duckdns.org` 를 입력해서 들어갑니다.
2. 화면 오른쪽 위 **로그인**(Google, GitHub 등 전에 쓰던 걸로)을 누릅니다.
3. 화면 가운데 **domains** 라는 표가 있습니다. 첫 칸에 `어쩌고` 라고 적혀 있고, 그 뒤에 `.duckdns.org` 가 붙어 있습니다.
   - 예: 표에 `stocknew` 가 있으면 우리 집 주소는 `stocknew.duckdns.org` 입니다.
4. **이 이름(주소)만** 적어 두세요.

> ⚠️ 같은 화면 위쪽에 **token**(긴 글자 줄)이 보입니다. **절대로 저에게 알려주면 안 돼요.** 그건 집 열쇠입니다.

### 확인 ② VM(우리 집)에 들어가는 방법

1. 윈도우 왼쪽 아래 **시작 버튼(⊞)** 을 누릅니다.
2. `PowerShell` 이라고 입력하고 **Enter**를 누릅니다. (파란색 또는 검은색 창이 열려요.)
3. 아래 글자를 **그대로 복사해서 붙여넣고 Enter**를 누릅니다.

```powershell
ssh stock-new
```

4. 이렇게 나오면 **성공**입니다. 줄 맨 앞이 `ubuntu@…:~$` 로 바뀝니다. (이제 VM 안에 들어온 거예요.)
5. 처음이면 `Are you sure you want to continue connecting?` 라고 물을 수 있어요. `yes` 라고 쓰고 Enter.
6. 나가고 싶을 때는 `exit` 라고 쓰고 Enter.

> 이 안내서에서 **"VM 안에서"** 라고 쓴 명령은 4번처럼 `ubuntu@…:~$` 가 보일 때 입력하는 것입니다.

### 확인 ③ 경비 아저씨(Caddy)가 있나?

**VM 안에서** 아래를 입력하고 Enter.

```bash
caddy version
```

- 숫자가 나오면(예: `v2.8.4`) → **있어요.** "Caddy 있음"이라고 적어 두세요.
- `command not found` 라고 나오면 → **없어요.** "Caddy 없음"이라고 적어 두세요. (→ 2번 단계에서 설치합니다.)

### 확인 ④ 문(포트 80, 443)이 열렸나? (두 군데를 봐야 해요)

문은 **두 겹**입니다. 집 안쪽 문과, 오라클 회사가 만든 바깥쪽 문. **둘 다** 열려야 합니다.

**(가) 집 안쪽 문 — VM 안에서:**

```bash
sudo iptables -L INPUT -n | grep -E "dpt:(80|443)"
```

- `ACCEPT ... dpt:80` 과 `ACCEPT ... dpt:443` 두 줄이 **나오면** → 안쪽 문 열림.
- **아무것도 안 나오면** → 안쪽 문 닫힘. (→ 2번 단계 B에서 엽니다.)

**(나) 바깥쪽 문 — 오라클 웹사이트에서:**

1. 인터넷에서 오라클 클라우드(`cloud.oracle.com`)에 로그인합니다.
2. 왼쪽 위 **☰ 메뉴** → **Networking(네트워킹)** → **Virtual cloud networks(가상 클라우드 네트워크)** 를 누릅니다.
3. 목록에서 우리 VM이 쓰는 네트워크 이름을 누릅니다. (하나뿐이면 그것)
4. **Security Lists(보안 목록)** → **Default Security List…** 를 누릅니다.
5. **Ingress Rules(수신 규칙)** 표를 봅니다. **Destination Port Range(대상 포트)** 칸에 `80` 과 `443` 이 있고, **Source(소스)** 가 `0.0.0.0/0` 인 줄이 각각 있으면 → 바깥쪽 문 열림.
6. 없으면 "닫힘"이라고 적어 두세요. (→ 2번 단계 B에서 엽니다.)

> 오라클 화면은 가끔 이름이 조금 달라요. 헷갈리면 **화면을 캡처해서 저에게 보내주세요.**

### 저(Claude)에게 알려줄 것 — 이 네 줄만 적어서 보내주세요

```
1) 우리 집 주소: ○○○○.duckdns.org
2) Caddy: 있음 / 없음
3) 안쪽 문(iptables): 열림 / 닫힘
4) 바깥쪽 문(오라클): 열림 / 닫힘 / 모르겠음(캡처 보냄)
```

---

## 2. 설치하기 (확인 결과에 맞는 것만 하세요)

모든 명령은 **VM 안에서**(`ubuntu@…:~$` 화면) 한 줄씩 복사해서 붙여넣고 Enter 하세요.
중간에 `[Y/n]` 하고 물으면 `Y` 를 쓰고 Enter.

### A. Caddy가 "없음"일 때만: 설치 (공식 홈페이지의 방법 그대로예요)

```bash
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
```
```bash
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
```
```bash
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
```
```bash
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
```
```bash
sudo apt update && sudo apt install caddy
```

끝나면 `caddy version` 을 입력해서 숫자가 나오는지 봅니다.

### B. 문이 "닫힘"일 때만: 문 열기

**집 안쪽 문 (VM 안에서)** — 두 줄을 차례로:

```bash
sudo iptables -I INPUT 1 -m state --state NEW -p tcp --dport 80 -j ACCEPT
```
```bash
sudo iptables -I INPUT 1 -m state --state NEW -p tcp --dport 443 -j ACCEPT
```

그리고 이 문이 컴퓨터를 껐다 켜도 남게 저장합니다:

```bash
sudo apt install -y iptables-persistent && sudo netfilter-persistent save
```
(중간에 파란 화면으로 "IPv4 규칙 저장할까요?" 하고 물으면 **Yes** 를 고르세요.)

**오라클 바깥쪽 문 (웹사이트에서)** — 1번 확인 ④(나)의 4번 화면까지 간 다음:

1. **Add Ingress Rules(수신 규칙 추가)** 버튼을 누릅니다.
2. **Source CIDR** 칸에 `0.0.0.0/0` 을 씁니다.
3. **IP Protocol** 은 `TCP`, **Destination Port Range** 칸에 `80` 을 씁니다.
4. **Add Ingress Rules** 버튼으로 저장합니다.
5. 같은 방법으로 `443` 도 한 번 더 합니다.

> 왜 80도 여나요? Caddy가 **인증서(안전 자물쇠)** 를 받으러 갈 때 80번 문을 쓰기 때문이에요.

---

## 3. 프로그램 설정하기 (이 부분은 저(Claude)가 코드를 올린 뒤에 합니다)

> 먼저 컴퓨터(PowerShell)에서 코드를 올려야 합니다. 이 순서는 저와 함께 진행해요. 아래는 **VM 안에서** 합니다.

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

**7) 프로그램을 켜기**
```bash
sudo cp deploy/autotrader-web.service deploy/autotrader-snapshot.service deploy/autotrader-snapshot.timer /etc/systemd/system/
```
```bash
sudo systemctl daemon-reload
```
```bash
sudo systemctl enable --now autotrader-web.service autotrader-snapshot.timer
```

**8) 경비 아저씨(Caddy)에게 우리 집 주소 알려주기**
```bash
sudo nano /etc/caddy/Caddyfile
```
- 파일이 열립니다. 안의 글자를 모두 지우고(`Ctrl+K` 를 여러 번), 아래를 붙여넣은 뒤 `우리집주소.duckdns.org` 자리에 **확인 ①의 주소**를 넣으세요.
- 저장: `Ctrl+O` → Enter, 나가기: `Ctrl+X`.

```
우리집주소.duckdns.org {
	encode gzip
	header -Server
	reverse_proxy 127.0.0.1:8787
}
```
```bash
sudo systemctl reload caddy
```

---

## 4. 폰에서 확인하기 (성공 체크리스트)

폰 브라우저(크롬·사파리)에서 `https://우리집주소.duckdns.org` 로 들어갑니다. (처음에는 자물쇠 받느라 몇 초 걸릴 수 있어요.)

- [ ] 주소창에 **자물쇠 🔒** 가 보인다.
- [ ] **로그인 화면**(비밀번호, 인증앱 코드 칸)이 보인다.
- [ ] 비밀번호 + 인증앱의 **6자리 숫자**를 입력하면 **요약 화면**이 나온다.
- [ ] 요약 화면에 **종목 이름·금액이 없다**(정상!).
- [ ] 아래 "보유·주문 상세 보기"를 눌러 인증앱 숫자를 **새로** 입력하면(30초 기다려서 바뀐 숫자) 보유·잔고가 나온다.
- [ ] 5분 뒤 다시 상세를 누르면 **또 숫자를 물어본다.**
- [ ] **로그아웃** 버튼을 누르면 로그인 화면으로 돌아간다.

---

## 5. 문제가 생겼어요 (증상별 안내)

| 이렇게 보이면 | 뜻 | 이렇게 해보세요 |
|---|---|---|
| 폰에서 **"연결할 수 없음"** / 계속 로딩 | 문이 닫혀 있거나 주소가 틀림 | 1번 확인 ④를 다시 보세요. 주소 글자도 확인하세요 |
| **"안전하지 않음"** 경고 | 인증서(자물쇠)를 아직 못 받음 | 1~2분 기다린 뒤 다시. 안 되면 VM에서 `sudo journalctl -u caddy -n 30` 결과를 캡처해서 저에게 |
| 로그인 화면에서 **"로그인할 수 없습니다"** | 비밀번호나 숫자가 틀림 (어느 쪽인지는 일부러 안 알려줘요) | 인증앱 숫자가 **바뀐 직후의 새 숫자**인지 확인. 5번 틀리면 15분 기다려야 해요 |
| **"잠시 후 다시 시도하세요"** | 잠금 | 15분 기다리세요 |
| **502 / Bad Gateway** | 안내판 프로그램이 꺼져 있음 | VM에서 `sudo systemctl status autotrader-web` 캡처해서 저에게 |
| 요약 화면의 **"스냅샷 없음"** | 잔고를 아직 못 읽음 | 3-5 (스냅샷) 다시. `~/collector-venv/logs/autotrader-snapshot.log` 캡처해서 저에게 |
| 인증앱 숫자를 **처음부터** 잃어버림 | 키를 다시 만들어야 함 | VM에서 `web-setup --reset` (3-6과 같은 방법으로 다시 등록) |
| 뭔지 모르겠음 | - | **화면을 캡처해서 보내주세요** |

## 6. 저(Claude)에게 절대 알려주면 안 되는 것

- DuckDNS **token**
- 웹 화면 **비밀번호**, 인증앱 **키(긴 영어·숫자)**, 인증앱의 **6자리 숫자**
- 증권사 **앱키·시크릿·계좌번호**
- 주소창에 `?key=` 가 들어간 주소

알려주셔도 되는 것은 **우리 집 주소(○○.duckdns.org)**, **화면 캡처(위 비밀이 가려진 것)**, **오류 글자**입니다.

---

## 7. 그만두고 싶을 때 (끄는 방법)

**VM 안에서** 한 줄이면 화면이 꺼집니다. (자동매매 자체는 영향 없음)

```bash
sudo systemctl disable --now autotrader-web.service
```
