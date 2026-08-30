---
track: kr
factor: intraday-data-source-study
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "한국 1분봉 소스 조사 - PRIMARY=KIS(무료, 1년), BACKUP=대신 CYBOS, 2016 소급은 무료로 불가(유료 견적 별도 트랙)"
---
# 한국 주식 1분봉 데이터 소스 연구 (2026-08)

목적: Research Lab이 장기적으로 재현 가능하게 사용할 1분봉(KOSPI/KOSDAQ) 원천 소스를 결정한다.
방법: ①저장소 내부 실측 증거(_probe-minute-kis.json, minute.v1.json, MN-1.0 계약) ②공식 문서/
      공식 Q&A/SDK 문서 웹 검색 교차. 실제 수집·API 호출 없음. 확인 못 한 값은 UNKNOWN 표기.

## 0. 프로젝트 요구사항 (선행 감사에서 확정)

- 필요 최소: 1분봉 OHLCV(raw 보존), 연구 해상도는 5분 리샘플 우선(intraday-data-requirements 참조)
- 대상: KOSPI/KOSDAQ(A1a 2,578종목), 기존 일봉 연구기간 2016~현재
- 제약: PIT 준수 · 수정주가 축은 A2a와 통일 · 폐지종목(A1b) 처리 · 외부 저장은 읽기 전용 정책 유지

## 1. 소스별 조사 결과

### KIS Open API — 주식일별분봉조회 [v1_국내주식-213] inquire_time_dailychartprice
| 항목 | 결과 | 근거 |
|---|---|---|
| 1분봉 | O | 우리 T0 프로브 실측(rowsPerCall=120) |
| 5/15분봉 | X(1분만 제공 → 리샘플) | 엔드포인트 사양 |
| 보존기간 | **최대 1년(공식)**. 실측 경계 2025-07-29@2026-08-09(=246거래일) | PyQQQ SDK 문서 인용("당사 서버 보관분만… 최대 1년 분봉 보관"), minute.v1.json |
| 과거 날짜 지정 | O(FID_INPUT_DATE_1) — 영업일전 5/20/60/120일 dateHonored=true 실측 | _probe-minute-kis.json |
| 전 종목 | O(Broad 2,453종목 설계, 일 562,974행 실측) | minute.v1.json |
| 폐지종목 | 미측정(T1 이관) | probe findings #11 |
| OHLCV | O(open/high/low/close/cntg_vol) | 실측 |
| 거래대금 | X — close×volume 파생만 | cntg_vol=구간 거래량(일합=A2a의 98.44%) 실측 |
| 수정주가 | 수정축 고정(파라미터 없음, A2a와 같은 축) | probe #5 확정 |
| timestamp | KST, **봉 시작시각 기준**(09:00 첫 봉, 15:30 단일가 봉), 장전 시간외 미포함 | probe #6 |
| 세션 누락 | 휴장일 요청 시 **다른 날짜로 치환 응답**(dateHonored=false) — 수집기가 기록 필수 | probe #8 실측 |
| rate limit | 초당 제한 존재(EGW00201). 프로브: 8~16 동시 버스트 무거부(실효 ~2/s) | probe #4, open-trading-api README |
| 대량 수집 | 가능 — 246거래일×2,453종목×평균 ~4콜/일 규모 | MN-1.2 설계 |
| 비용/key | 무료(계좌+앱키). 모의계좌는 제한 더 낮음 | portal, open-trading-api README |
| 재현성/PIT | 즉시 재조회 동일 확인. **과거 재조회 시 값 변화(리베이스) 여부는 미측정(T1)** | probe #12/#11 |
| 문서↔실측 불일치 | 페이지 크기: PyQQQ 문서 표기 100건 vs 우리 실측 120건(minute.v1.json은 "문서값과 일치"로 기록) — 양쪽 다 기록 | - |

### 키움 OpenAPI opt10080 / REST ka10080
- 1/3/5/10/15/30/45/60분봉 지원, 수정주가구분 선택 가능(devsalix 블로그, ka10080 문서)
- 보유 기간 **약 1년**(커뮤니티 실측 블로그 i-whale, 2024) — 공식 수치 미확인(UNKNOWN)
- 기간 명시 조회 불가 → 최신부터 블록 연속조회(next=2). REST ka10080은 기본 900개,
  장기 과거 조회 실패 보고 존재(네이버 지식iN 답변+질문)
- Windows 전용(OCX), 계좌 필요, 무료. rate limit: TR당 초당 제한(공식 수치 UNKNOWN)

### 대신증권 CYBOS Plus(CpSysDib.StockChart) / Creon Plus — **무료 중 최장 retention 후보**
- Creon 공식 Q&A 담당자: "**분봉 데이터는 최대 2년까지 제공**합니다. 연속 조회 이용"
- Creon-Datareader GitHub(2018): 1분봉 약 18.5만 개(≈2년), 5분봉 약 9만 개(≈5년)
- trustyou 블로그 인용 운영진 답변: 1분봉 2년 / 5분봉 5년 / 틱봉 20일
- **⚠️ 단, 2026-03-20 사이보스플러스 Q&A 사용자 보고: "얼마 전까지 1분봉 2년·5분봉 5년이었는데
  오늘 확인하니 모든 분봉 약 1년 치만 수집 가능"** — 축소 정황. 공식 확정 없음 → **계약 전 재측정 필수**
- 회당 최대 2,499개 + 연속조회, **거래량+거래대금(tvol) 직접 제공**, 수정주가 on/off 선택,
  갭보정 옵션 — KIS에 없는 두 기능
- Windows 전용, 계좌 필요, 무료

### Yahoo Finance (yfinance) — 부적합
- 1m: 최근 30일 내만, 요청당 7일 청크(gitHub issue #356, stackoverflow 실측답변)
- 5m/15m/30m/90m: 최근 60일, 60m: 최근 730일(yfinance history.py 소스 min_lookbacks)
- .KS/.KQ 지원하나 타임존·누락 이슈(discussion #1877), 비공식 엔드포인트(무 SLA) →
  장기 재현성·PIT 관점 부적합

### pykrx / KRX 정보데이터시스템(무료)
- get_market_ohlcv frequency d/m/y만 — **intraday 없음** (GitHub README)
- KRX 무료 사이트도 일별까지만 제공; 분봉 이하는 유료 구매 대상(koapy 문서:
  "일별 시세정보 1996~2021 = 3,775,000원" 유료 견적 예시, "분봉 이하는 별도 구매")

### Naver Finance fchart
- pykrx naver core·pandas-datareader 코드상 timeframe day/week/month만 — minute 미문서화.
  커뮤니티에 minute 사용례가 알려져 있으나 본 조사에서 공신력 있는 근거 미확보 → **UNKNOWN**

### KRX 유료 / 기타 유료 벤더
- KRX DATA 등 유료 상품에 분봉 존재 여부·가격·전달 형식: **미확인(견적 필요)**.
  무료 경로로 2016 소급이 불가능함이 확정된 상태라, 유일한 남은 HISTORICAL 경로다.

## 2. retention 상세 검증 요약

| 소스 | 1분봉 보존 | 요청당 최대 | 과거 날짜 지정 | 무료/유료 |
|---|---|---|---|---|
| KIS | 최대 1년(공식+우리 실측 246거래일) | 120건/호출(실측; 문서 100건 표기 혼재) | O | 무료 |
| 키움 | 약 1년(커뮤니티, 공식 미확인) | 블록 단위(REST 기본 900개)+연속조회 | X(역순 페이지네이션만) | 무료 |
| 대신 CYBOS | 공식 답변 2년(2018~2024 문헌), **2026-03 ~1년 축소 보고** — 재측정 필요 | 2,499개+연속조회 | X(개수 기반 역순) | 무료 |
| Yahoo | 최근 30일(7일 청크) | 7일 | X | 무료(비공식) |
| KRX 무료 | 없음(일별만) | - | - | 무료 |
| KRX 유료 | UNKNOWN(견적 필요) | - | - | 유료 |

## 3. 용도별 선정

- **A. 지금 당장 확보**: KIS — 커넥터·정책·프로브·VM 배포 유닛까지 이미 검증 완료(MN-1.2).
  246거래일 창이 매일 1일씩 닫히므로 최우선 실행 항목.
- **B. 과거 장기 백필(2016 소급)**: **무료 경로로는 원천 불가능(확정)** — 모든 무료 소스가
  ≤2년. 옵션: ①KRX DATA 등 유료 견적 조사(가격 미확인) ②CYBOS 2년 생존 재측정 성공 시
  2024~2026 커버리지 확장 ③소급 포기하고 지금부터 축적.
- **C. 향후 지속 수집**: KIS daily job(MN-1.2 + deploy/minute-collect.{service,timer} 설비 존재).

## 4. 1m → 5m 파이프라인 설계 (코드 없음)

```
raw 1m parquet (minute/date=YYYY-MM-DD/part-*.parquet, zstd — MN-1.2 그대로)
  → PIT-safe 저장: 장 마감 후 수집, dateHonored/gapReason(HALT·HOLIDAY·PRE_LIST·EMPTY)
    기록, staging→acceptance 통과 후 확정(교훈43)
  → 품질검사: low<=high, open∈[low,high](09:00 봉 예외), Σvolume vs A2a 일량 ±2%,
    캔들 수 vs 세션 381분, 중복 제거(커서 겹침 1건 실측)
  → 5m resample: 세션 경계 09:00/10:30/12:00/13:30/14:50/15:19(+15:30 단일가 봉),
    15:20~29는 결측이 아니라 '세션 없음'으로 처리
  → strategy-lab PriceProvider: minute PriceProvider 신설 + FastBars ts축 확장
```

정의:
- **timestamp convention**: KST naive, **봉 시작시각 라벨**(KIS 실측: 09:00 캔들이 첫 봉).
  15:30 봉은 종가단일가. 15:20~29는 존재하지 않는다(누락 아님).
- **거래일 calendar**: A0.5 calendar.json과 일치 검증(휴장일 치환 응답 방어).
- **결측 1분봉**: 무체결 분은 raw에 행을 만들지 않고 gapReason으로만 기록(교훈75 raw-only);
  ffill은 파생층에서만.
- **거래정지**: rows=0 → gapReason=HALT. 재수집 여부는 pendingT1 블록으로 격리돼 있다.
- **상장/폐지**: A1b(delisted.jsonl)와 조인해 폐지 종목은 수집 스킵+기록. 신규상장은
  listedAt 이후부터.
- **수정주가**: 소스 수정축을 raw 그대로 보관(A2a와 동일 축이라 호환). 단 "같은 날짜를
  나중에 다시 받으면 과거값이 바뀌는가"(probe #11 미측정)를 T1에서 반드시 확인하고,
  바뀐다면 raw 스냅샷 불변 원칙 + adjust_factor 별도 테이블로 대응.
- **volume/turnover**: interval volume 그대로(raw). turnover는 close×volume 근산화는
  파생층 몫(CYBOS를 쓰게 되면 tvol 직접값으로 교체).

## 5. 용량 계산 (출발점 = MN-1.0/1.2 실측: Broad 562,974행/일, 1.38억행/년, parquet 1.52GB/년)

| 보관 기간 | 행 수(추정) | parquet(추정) | 비고 |
|---|---|---|---|
| 1년 | ~1.38억 | **~1.52GB (실측)** | Broad 전종목 기준 |
| 3년 | ~4.14억 | ~4.6GB (추정) | |
| 5년 | ~6.9억 | ~7.6GB (추정) | |
| 10년 | ~13.8억 | ~15GB (추정) | MN-1.0 "200GB 블록볼륨이면 수십 년치" |

5분 리샘플은 각각 ÷5(~0.3GB/년). 실측은 1년치만 검증됐고 나머지는 선형 외삽이다.

## 6. 최종 권고

- **PRIMARY (= LIVE)**: KIS Open API inquire_time_dailychartprice — 무료, 공식 보존 1년,
  우리 커넥터/프로브/정책/배포 설비까지 완비된 유일한 소스. 매일 Broad 적립 즉시 가동.
- **BACKUP**: 대신증권 CYBOS Plus — retention이 2년일 가능성(단 2026-03 축소 보고 있어
  **계약 전 소수 종목 재측정 필수**) + 거래대금 직접 제공 + 수정/원주가 선택. Windows 의존이 단점.
- **HISTORICAL (2016 소급)**: **무료 경로로는 불가능(본 연구에서 확정)**. 유일한 경로는
  KRX DATA 등 유료 상품(가격·형식 미확인 — 견적 조사를 별도 트랙으로). 실패를 전제해
  2024~2026 구간부터의 축적(CYBOS 2년 + KIS 적립)을 시작한다.
- **LIVE**: PRIMARY와 동일(KIS). Yahoo·Naver는 백업 가치도 낮음(보존 짧음/비공식).

### 명확한 답
"Research Lab이 지금부터 장기적으로 사용할 1분봉 원천은 **KIS Open API의
inquire_time_dailychartprice로 매일 Broad(전 종목) 1분봉을 장 마감 후 적립**하는 것이
가장 현실적이다 — 무료이고 공식 보존이 1년으로 확인되며 우리 수집 설비(MN-1.2)가 이미
그 소스에 맞춰 검증돼 있다. 과거 2016년까지의 소급은 국내 무료 소스로는 불가능함이
확인됐으므로, 유료 상품 견적(KRX DATA 등)을 별도 트랙으로 조사하되 그 결과와 무관하게
적립을 즉시 시작한다. 5분봉은 별도 수집 없이 1분 raw에서 리샘플한다."

## 출처
- 저장소 내부(1차 실측): data/backfill/_probe-minute-kis.json · research/strategy-lab/findings/intraday-data-inventory-2026-08.md · config/policies/minute.v1.json(MN-1.2) · docs/MN-1.0-분봉Raw저장계약.md
- KIS Developers 공식 문서(apiportal.koreainvestment.com) 및 PyQQQ SDK 문서(docs.pyqqq.net, inquire_time_dailychartprice — "최대 1년 분봉 보관")
- koreainvestment/open-trading-api GitHub(EGW00201·모의계좌 제한)
- Creon 공식 Q&A(money2.creontrade.com — "분봉 최대 2년") · 대신 사이보스 Q&A(money2.daishin.com — 2026-03-20 축소 보고) · gyusu/Creon-Datareader GitHub
- devsalix 블로그(opt10080 사양) · i-whale 블로그(키움 1년·페이지네이션) · 네이버 지식iN(ka10080 900개)
- yfinance GitHub(issue #356, discussion #1877, history.py 소스) · sharebook-kr/pykrx README
- koapy.readthedocs.io(KRX 정보데이터시스템 유료 견적 사례)
