# 설치 및 운영 가이드

GitHub 저장소 하나로 "매일 자동 분석 + 웹 대시보드 + 알림"이 돌아가는 구조입니다.
서버·API 키 없이 시작할 수 있고, **PC를 꺼도 GitHub Actions가 대신 실행합니다.**

## 구조 한눈에 보기

```
[GitHub Actions - 평일 16:40 KST]  daily-analysis
  collect.js (KR: 네이버 / US: Stooq 시세·수급 수집)
    → analyze.js (스코어링·국면·포트폴리오 신호·추천기록·이력스냅샷)
    → docs/data/*.json 커밋
    → notify.js (텔레그램/슬랙 알림)

[GitHub Actions - 장중 10분 간격]  intraday-alert
  intraday-check.js (열린 시장 판별 → 급등락 감지 → 즉시 알림)

[GitHub Actions - 일요일 17:00 KST]  weekly-backtest
  backtest-report.js (누적 이력으로 KR/US 시장별 백테스트) → 커밋

[GitHub Pages]
  docs/index.html 이 docs/data/*.json 을 읽어 대시보드 표시
```

## 1. 저장소 만들기

1. GitHub에서 새 저장소 생성 (예: `stock-scoring-app`).
   ⚠️ intraday-alert를 10분 간격으로 쓰려면 **Public 권장** (Actions 무제한).
   Private는 무료 한도 월 2,000분이라 장중 감시까지 돌리면 빠듯합니다.
   Public으로 쓸 경우 holdings.json에 실제 보유 수량을 넣을지는 신중히 판단하세요.
2. 이 폴더 전체를 업로드:
   ```bash
   cd stock-scoring-app
   git init && git add . && git commit -m "initial"
   git branch -M main
   git remote add origin https://github.com/<계정>/<저장소>.git
   git push -u origin main
   ```

## 2. GitHub Pages 켜기

저장소 → Settings → Pages → Source: `Deploy from a branch`, Branch: `main` / `/docs` → Save.
몇 분 후 `https://<계정>.github.io/<저장소>/` 에서 대시보드가 열립니다.

## 3. Actions 권한 확인

Settings → Actions → General → Workflow permissions → **Read and write permissions** 선택.
(분석 결과를 저장소에 커밋하기 위해 필요)

## 4. 첫 실행

Actions 탭 → `daily-analysis` → Run workflow (수동 실행).
성공하면 `docs/data/`의 샘플 데이터가 실제 수집값으로 교체되고 대시보드에 표시됩니다.
이후엔 평일 16:40(KST)에 자동 실행됩니다.
※ 미국 종목은 fundamentals.json을 채우기 전까지 커버리지 부족으로 "유보" 등급이 정상입니다.

## 5. 알림 설정 (선택)

Settings → Secrets and variables → Actions → New repository secret:

| Secret 이름 | 값 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | @BotFather에서 봇 생성 후 받은 토큰 |
| `TELEGRAM_CHAT_ID` | 봇과 대화 시작 후 `https://api.telegram.org/bot<토큰>/getUpdates`에서 확인 |
| `SLACK_WEBHOOK_URL` | Slack Incoming Webhook URL |

일일 알림 조건: 등급 변동, 신규 B등급 이상, 경고 플래그 신규 발생, 국면 caution/risk.

## 6. 장중 급등락 감시 (intraday-alert)

PC 없이 GitHub 서버가 장중에 10분 간격으로 가격을 체크합니다.

| 항목 | 내용 |
|---|---|
| 감시 시간 | 한국장 09:00~15:40 KST, 미국장 09:30~16:00 ET (자동 판별) |
| 감지 규칙 | 전일 대비 ±5% (`dailyMovePct`), 직전 체크 대비 ±3% (`suddenMovePct`) |
| 재알림 제한 | 같은 종목·같은 규칙 90분 쿨다운 |
| 규칙 수정 | `scripts/intraday-check.js` 상단 `RULES` 상수 |
| 간격 조정 | `.github/workflows/intraday-alert.yml`의 `*/10` (한도 부족 시 `*/20`) |

**한계와 보완**: 이 방식은 "10분 간격 + Actions 실행 지연 1~3분"이라 초 단위 실시간이
아닙니다. 더 빠른 알림이 필요하면 **증권사 MTS 앱의 조건 알림을 병행**하세요
(한국투자/키움 앱 → 알림 설정 → 종목별 등락률/지정가 도달 푸시 - 증권사 서버가 실시간
전송, 코드 불필요). 초 단위 자동 처리가 필요해지면 KIS Developers 웹소켓 + 상시 구동
머신(오라클 프리티어 등)으로 업그레이드하는 게 다음 단계입니다.

## 7. 일상 운영

| 작업 | 방법 | 주기 |
|---|---|---|
| 관심종목/그룹 추가·삭제 | `config/watchlist.json` (market: KR/US, groups) | 수시 |
| 보유종목 갱신 | `config/holdings.json` (수량/평단) | 매매 후 |
| 재무 데이터 갱신 | `config/fundamentals.json` (US는 per/pbr 포함) | 분기 1회 |
| 버핏 13F 그룹 갱신 | 분기 13F 공시 확인 후 watchlist 수정 | 분기 1회 |
| 거시 판단 갱신 | `config/macroInput.json` (환율은 자동) | 주 1회 권장 |
| 가중치 튜닝 | `config/criteria.json` / `criteria-us.json` — 백테스트 근거로만 | 백테스트 확인 후 |

재무 데이터 출처 - KR: FnGuide(comp.fnguide.com)·네이버금융(빠름), DART(원천) /
US: stockanalysis.com·macrotrends.net(빠름), SEC 10-K(원천).

## 8. 백테스트가 의미를 갖는 시점

- 매일 스냅샷이 `docs/data/history/`에 쌓입니다 (KR/US 모두).
- 약 1개월 후: 20일 수익률 표본 생성 시작 → 첫 백테스트 결과 (KR↔KOSPI, US↔S&P500 비교)
- 약 3~6개월 후: 표본 100건 이상 → IC·등급 단조성을 근거로 가중치 조정 가능
- **A등급이 거래비용 차감 후 벤치마크를 못 이기면 가중치를 바꾸거나 이 시스템을
  참고용으로만 쓰세요. 그게 이 탭의 존재 이유입니다.**

## 데이터 소스 교체 (수집이 깨졌을 때)

비공식 소스(네이버/Stooq)가 바뀌면 Actions 로그에 `[경고] ... 수집 실패`가 반복됩니다.
`scripts/collect.js`의 해당 함수만 교체하면 됩니다:

- KR 일봉: `fetchDailyCandlesKR()` — KRX 정보데이터시스템 또는 증권사 Open API
- US 일봉: `fetchDailyCandlesUS()` — Yahoo Finance, Alpha Vantage 등
- KR 밸류에이션: `fetchValuationInfoKR()` / KR 수급: `fetchSupplyDemandKR()`

수집이 일부 실패해도 파이프라인은 죽지 않고 해당 필드만 결측 처리됩니다.

## 이 저장소에 넣지 않은 것 (의도적)

- **초 단위 실시간 감시**: Actions 구조상 불가. 위 6번의 MTS 조건 알림 병행 또는
  KIS 웹소켓 + 상시 구동 머신으로 해결.
- **자동매매**: 증권사 API 키를 GitHub에 두는 것은 권장하지 않으며, 스코어가 백테스트로
  검증되기 전에는 자동 주문의 근거 자체가 없습니다. 검증 후에도 로컬 실행을 권장합니다.

## ⚠️ 면책

이 시스템은 정보 통합·정량화 참고자료 생성기이며 투자 자문이 아닙니다.
모든 매매 판단과 그 결과에 대한 책임은 사용자 본인에게 있습니다.
