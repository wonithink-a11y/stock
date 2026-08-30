---
track: crypto
factor: positioning-data-audit
date: 2026-08-29
verdict: UNCLASSIFIED
original_verdict: FAIL
criteria_version: backfill-v1
conditions: ["globalLongShortAccountRatio", "topLongShortAccountRatio", "topLongShortPositionRatio", "takerlongshortRatio", "startTime 경계 30일"]
reason: "Binance futures positioning 4종 API가 전부 최근 ~30일만 보유(startTime now-60d부터 -1130) - 2023-05~ 연구기간과 비겹쳐 장기 정보축 편입 불가, 판정 FAIL"
---
# Step 21 — Futures Positioning(Long/Short Ratio) 데이터 가용성 감사

날짜: 2026-08-29 | 판정: **FAIL**

## 설계

- Binance USDⓈ-M Futures 공개 Market Data API 4종을 **실제 호출**로 감사
  (대량 다운로드 없이 probe/metadata만, 총 186회 호출).
- 요청 간 1.4s 페이싱, 밴(418/-1003) 수신 시 즉시 중단 — 이번 실행은 밴/429 없이 완료
  (Step 18 basis IP밴 경험 반영, 과도한 조회 금지).
- startTime 경계는 `-1130(parameter startTime is invalid)` 오류 유무로 판정(Step 16 OI와 동일 방식).
- 기존 funding/basis/OHLCV/S2/전략/findings 수정 없음. 신규 파일만 생성.

## 결과

### 1) 4개 엔드포인트 공통
| endpoint | 인증 | symbols | intervals |
|---|---|---|---|
| `GET /futures/data/globalLongShortAccountRatio` | 필요 없음(공개) | 28/28 OK | 5m·15m·30m·1h·2h·4h·6h·12h·1d (9종) |
| `GET /futures/data/topLongShortAccountRatio` | 필요 없음(공개) | 28/28 OK | 〃 |
| `GET /futures/data/topLongShortPositionRatio` | 필요 없음(공개) | 28/28 OK | 〃 |
| `GET /futures/data/takerlongshortRatio` | 필요 없음(공개) | 28/28 OK | 〃 |

- 커버리지: 대표 7종목(BTC ETH SOL DOGE NEAR BNB 1000PEPE) + 나머지 21종목 전부 `ok`.
- 데이터 의미: global = 전 거래자 Long/Short 계좌수 비율; top account = 상위 거래자 계좌수;
  top position = 상위 거래자 포지션 계약량; taker = 매수/매도 체결량 비율(`longAccount/shortAccount`,
  `longPosition/shortPosition`, `buyVol/sellVol`, `longShortRatio`, `timestamp`).

### 2) 보유 깊이 — **전부 최근 ~30일 한정** (핵심 발견)
| endpoint | 1d limit1000 (no startTime) | 1h limit1000 (no startTime) |
|---|---|---|
| global | count=31, span 30.0일 (2026-07-30→08-29) | count=744, span 30.96일 |
| top account | count=31, span 30.0일 | count=744, span 30.96일 |
| top position | count=31, span 30.0일 | count=744, span 30.96일 |
| taker | count=31(최신 08-28, 1d 마감 1일 지연), span 30.0일 | count=744, span 30.96일 |

- 모두 `strictly_increasing`(내부 중복/결측 없음, probe 범위).
- limit=1000을 줘도 31일치(1d)/31일치(1h)만 반환 → **API 자체가 최근 30일만 보관**.

### 3) startTime 경계 (BTC, global·taker)
| startTime | 결과 |
|---|---|
| now−30d | OK (반환됨) |
| now−60d | `-1130 parameter 'startTime' is invalid` |
| now−180d·−365d·−730d·−1095d | 〃 전부 오류 |
| **2023-05-01 / 2021-01-01 / 2019-09-01** (직접) | **전부 `-1130` 오류** |

→ `startTime`은 **지원하되 지난 30일 안에서만** 의미. 연구 기준일 2023-05-21 이전은 물론,
2023년 어느 시점도 조회 불가.

### 4) 그 외 질문 항목
- **pagination**: 가능 — `startTime`/`endTime` 슬라이딩. 검증: 1일 윈도우(`startTime=now-3d, endTime=now-2d`) → 정확히 1행 반환.
- **limit**: 실측 최대 1000행 반환(limit=1000 probe 성공); 문서상 한도보다 관대했으며 윈도우가 30일이라 실질 한도는 보유량.
- **rate limit**: docs 기준 weight 기반; 실측으로 186회를 ~4분 소요(≈0.4 req/s, 1.4s 페이싱)로 무밴 진행. 이 계열(`/futures/data/*`)은 Step 18에서 반복 호출 시 IP 밴(`-1003 banned until`)이 실측된 바 있어 **대량 수집 금지**.
- **timestamp 기준**: UTC epoch ms, **period 시작 시각**. 1d bar = 00:00 UTC 시작.
- **KST 결합**: UTC→+9h로 funding/basis와 동일한 방식(period 시작 시각 기준)이면 결합 구조는 성립하나, **보유 30일 때문에 기존 연구기간(2023-05-21~)과 겹치지 않음**.

## 판정: **FAIL**

### 핵심 질문 답
1. **OI와 똑같이 최근 30일만 제공되는가?** → 예. 4개 엔드포인트 전부 ≈30일 (1d 31행 / 1h 744행),
   startTime now-60d부터 `-1130`. Step 16 `openInterestHist`와 동일 한정.
2. **Funding/Basis처럼 장기 히스토리가 있는가?** → 아니다. funding은 2019-09~ 장기, basis는
   Step 18에서 장기 반환(실측 폭은 IP밴으로 미완료)이었지만, positioning 4종은 장기 히스토리는커녕
   2023-05(기준일)부터도 조회 불가.
3. **28종목 공통 사용 가능한가?** → **가능**. 28/28 전부 OK (이 점만 PASS급).
4. **4종이 서로 독립 정보인가 구조적으로 판단 가능한가?** → 30일 내에선 가능하나
   기존 연구기간과 무관. 결론적으로 평가 대상이 아님.
5. **향후 연구 가치?** → 현재 형태로는 **없음**. 30일 윈도우는 크로스섹션 주간/월간 시그널 연구에
   쓰이던 기존 파이프라인(2023-05-21~ 샘플)과 결합 불가. 실거래 전용(rolling 30d) 배치 신호로만
   제한적으로 가능하나, 그 경우도 takerlongshort는 1d 직전일 마감 지연 + 전 종목 비용 무시 이슈.

### 결론
- funding(2019~)·basis·OHLCV의 **장기 정보축 파이프라인에는 편입 불가** — 연구기간 미충족.
- 만약 향후 "최근 30일 실시간 크로스섹션 신호"가 요구되면 재검토 가능하나 그건 별도 모듈이고
  이번 감사 판정은 **FAIL**.
- 신규 산출물: `positioning_data_audit.py` + `findings/positioning-data-audit-2026-08.{json,md}`.

## 부산
- 기존 데이터/findings/S2/engine 무수정, 백테스트·최적화 없음, 커밋 없음.
- 침습 최소화: 186호출 + 1.4s 페이싱, 밴 없이 종료. 이 계열 재호출 시 과도한 반복 금지 권고(Step 18 밴 기록).