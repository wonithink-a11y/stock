---
track: kr
factor: intraday-data-inventory
date: 2026-08-22
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["data/backfill 전 디렉터리", "manifest 12종", "KIS 분봉 프로브", "A2a/A2b 스키마", "A4 해상도"]
reason: "저장소 커밋 데이터는 전부 일봉 이하 해상도이고 장중 가격·체결·호가 원본은 0건임을 전역 검색으로 실측 - 분봉 수집 인프라(MN-1.2·커넥터 v1)만 완성 상태로, 단기 연구는 일봉 해상도 TIER 1~3 활용 가능"
---
# 단기·초단기 매매 연구용 데이터 재고 감사 — 장중/intraday 특화 (2026-08)

질문: "우리가 이미 받은 데이터 중 단기·초단기 연구에 쓸 수 있는 것을 놓치고 있는가?"
방법: data/backfill 전 디렉터리 + manifest 12종 + 수집기/프로브/정책 스크립트 실독 +
      저장소 전역 파일 검색(parquet·minute·intraday). 읽기 전용, 신규 수집 없음.
선행 문서: findings/data-field-inventory-2026-08.md (필드 의미 감사) — 본 문서는 그 위에
"시간 해상도" 축을 추가로 감사한 것.

## 결론 요약

**이 저장소에 커밋된 원본 데이터는 전부 일봉(day) 또는 그보다 낮은 해상도다.
장중(intraday) 가격·체결·호가 데이터는 1건도 존재하지 않는다.**
분봉 수집 인프라(정책 MN-1.2·커넥터 v1·KIS 프로브·VM 배포 유닛)는 완성 단계까지
검증돼 있으나, 계약상 raw parquet은 저장소 밖(VM 블록볼륨+OCI)에 두기로 되어 있고
로컬 저장소에는 분봉 원본이 0건이다(전역 검색으로 확인).

## 조사 근거 (파일·경로 실측)

| 확인 대상 | 실측 결과 | 근거 위치 |
|---|---|---|
| 분봉 디렉터리/파일 | 없음(`*minute*` 디렉터리 0, `data/**` parquet 0) | 전역 Get-ChildItem 검색 |
| 분봉 manifest stage | 없음(A0.5~A8만 존재) | data/backfill/manifest/ |
| 분봉 정책·커넥터 | 존재(MN-1.2, collect-minute-kis.py v1 "커넥터만") | config/policies/minute.v1.json, scripts/ |
| 분봉 raw 저장 계약 | **저장소 밖**(VM 블록볼륨+OCI Object Storage), Git에는 manifest만 | docs/MN-1.0-분봉Raw저장계약.md §1 |
| KIS 분봉 프로브 실측 | T0 API 페이지 120건·보존 최대 ~1년 등 12개 항목 측정 완료 | data/backfill/_probe-minute-kis.json (2026-08-09) |
| 분봉 유니버스 설계 | 턴오버 구간(A~G)별 표본 캔들수 381实测 | data/backfill/_probe-minute-coverage.json |
| tick/체결 수집 시도 | 흔적 없음(스크립트·정책·프로브 전무) | scripts/ 전수 목록 확인 |
| 호가 수집 시도 | 흔적 없음 | 동상 |
| A2a/A2b 스키마 | open/high/low/close/volume **일봉만** | a2aProvider._SCHEMA_FIELDS, 샘플 레코드 |

## 카테고리별 판정

### A. 장중 가격 데이터 — **저장소 내 없음**
- 1분/3분/5분/10~30분봉: **DATA GAP(저장소)**. 다만 인프라·계약·프로브는 완비.
  KIS 보존 한계(~1년, 프로브 실측) 때문에 소급 백필은 불가하고 "오늘부터 매일"만 축적 가능.
- 기타 intraday OHLCV / timestamp 가격: 없음.

### B. 체결 데이터 — **없음**
- 개별 체결(tick)/체결시각/방향/체결강도: 없음.
- A4의 buyVolume/sellVolume은 **일별 집계 체결량**(투자자구분별, field-inventory에서
  의미 확인 완료)이지 체결 스트림이 아니다. 누적체결량 필드도 없음(당일 총합만).

### C. 호가/시장미시구조 — **없음 (수집 시도 흔적도 0)**
- bid/ask 잔량·spread·imbalance·매수/매도벽 원천: DATA GAP 확정.

### D. 장중 파생 원천 — **일 단위까지만 가능**
- 장중 고가/저가: 일 high/low만 존재(장중 경로 알 수 없음).
- intraday VWAP 원천: A4 금액/수량으로 **일별 VWAP**만 파생 가능(이미 V6에서 외국인+
  기관 매수 VWAP로 부분 사용). 시간축 VWAP 궤적은 불가.
- 거래량·거래대금 급증: 일별 대비는 가능(A2a volume, A4 buyAmount['전체']).
- opening range·시간대별 분포: 원천 부재로 불가.

### E. 장중 수급 — **없음**
- A4는 장 마감 후 확정치라 장중 사용은 PIT 위반. 시간대별/실시간 투자자 데이터 없음.
- 프로그램 매매: 전무.
- docs/data/market_flows.json: pykrx 시장**전체** 일별 순매수(외국인/개인/기관세분)의
  롤링 최근분 대시보드 — 종목별 아님, 이력 백필 아님, 백필 데이터셋 아님.

### 참고: 거래정지·관리종목
- data/goldenset/market-actions-snapshot.json: 거래정지 127·관리 113·투자경고 28 종목
  스냅샷(2026-08-02 단발). 이력이 없어 PIT 연구엔 부적합, 현재 상태 참고만 가능.

## 기존 inventory(data-field-inventory-2026-08.md)와 대조

1. 이미 확인된 데이터(해상도 재확인): A1a/A1b/A2a/A2b/A3/A3B/A3C/A3D/A4/A8 — **전부 일봉
   또는 이벤트 단위**. A2a/A2b는 일봉 OHLCV만 확인됨(장중 데이터 아님을 명시).
2. 이번 신규 발견: 없음(장중 데이터는 발견되지 않았다). 보완 사실 ① 분봉 raw는 저장소 밖
   VM에만 존재하도록 계약됨 ② KIS 분봉 보존 ~1년 실측 ③ market_flows.json은 종목별
   데이터가 아니라 시장 전체 롤링 파일이라는 점 ④ 거래정지/관리 스냅샷 존재(단발).
3. 존재하나 의미 불명확: 해당 없음(장중 범위에서는 존재 자체가 없음). 일별 데이터의
   UNKNOWN 항목은 선행 inventory 참조(exitReason, dartModifyDate, rawIcMthn/rawCrMth).
4. 존재하지 않음으로 확정: 분봉·tick·호가·체결강도·프로그램매매·시간대별 수급(위 A~E).

## 최종 분류

### TIER 1 — 즉시 활용 가치 높음 (단기 연구 기준, 현 보유분)
요청 예시의 "장중 거래량/거래대금"에 해당하는 것은 없으며, 아래는 **일봉 해상도에서
즉시 쓸 수 있는 단기 연구 세트**다.
1. A2a 일봉 OHLCV (2,558종목, 2014-05~2026-08) — 갭·당일 박스(high-low)·종가 모멘텀
2. A4 buyAmount/sellAmount 카테고리별 금액(원) — 투자자별 수급 방향·크기
3. A4 buyVolume/sellVolume 카테고리별 수량(주) — 스케일 왜곡 없는 수급 비율
4. A4 파생 일별 VWAP(금액/수량) — 수급 참여가 vs 종가 괴리
5. A4 buyAmount['전체'] 거래대금 — 유동성·급증 필터

### TIER 2 — 단기 연구에 유용
6. A8 공매도 잔고(shortBalanceShares/Value) — 압력·스퀴즈 후보(공표 지연은 미측정,
   PIT 적용 시 확인 필요)
7. A8 shortVolume/shortValue — 하락일 원인 분해(수급 청산 vs 공매도)
8. docs/data/market_flows.json — 시장 국면(롤링 최근분, 종목별 아님)
9. A3C 주식수 — 정확 턴오버/시총 근사(일봉 전략의 유동성 정규화)

### TIER 3 — 중단기 보조
10. A3/A3B 펀더멘털(opProfit·currentAssets/currentLiab·eps·dividendPerShare)
11. A1a sector/market 라벨 — 업종 중립
12. A3D 기업행사 multiplier — 조정 계수 원천

### DATA GAP (저장소 원본에 없음이 확인된 것)
- 분봉 OHLCV(raw) — 인프라 완성, raw 오프사이트만 존재
- tick/체결 스트림(체결시각·방향·체결강도)
- 호가 잔량/spread/imbalance(수집 시도 자체가 없음)
- 프로그램 매매
- 시간대별 투자자 수급
- opening range 원천(장 초반 분봉)

## 전략 유형 연결

| 전략 유형 | 판정 | 근거 |
|---|---|---|
| 돌파 | **제한적으로 가능** | 일봉 저항 돌파(종가>전일 high 등)는 가능. 장중 레벨 터치·돌파 확인은 분봉 부재로 불가 |
| 눌림목 | 일봉은 가능(D) / 장중 눌림목 불가 | 일봉 pullback 정의만 성립 |
| VWAP | **제한적으로 가능** | 일별 VWAP(A4 금액/수량)만. 장중 VWAP 궤적 불가 |
| 거래량 급증 | **가능(일별)** | A2a volume·A4 거래대금의 과거 분포 대비 z-score |
| opening range | 불가 | 장 초반 분봉 부재 |
| 체결 momentum | 불가 | tick/체결 스트림 부재 |
| 매수/매도 imbalance | 일별만 가능(D) / 장중 불가 | A4 투자자별 (buy−sell)/(buy+sell) |
| 호가 imbalance | 불가 | 호가 데이터 전무 |
| 초단기 수급 | 불가 | 최소 해상도가 '일'이며 장중 사용은 PIT 위반 |

## TOP 10 / DATA GAP TOP 10 / 우선순위

### 1. 현재 저장소에 있는 가장 가치 높은 단기·초단기 데이터 TOP 10
1. A4 카테고리별 매수/매도 금액(원) — 투자자별 방향·강도
2. A4 카테고리별 매수/매도 수량(주) — 스케일 왜곡 제거 수급 비율
3. A4 파생 일별 VWAP — 수급 참여가 신호
4. A4 '전체' 거래대금 — 유동성·급증 게이트
5. A2a 일 high/low — 당일 변동폭·갭 계산
6. A2a volume — 거래량 급증 이력 비교
7. A8 공매도 잔고 수량/금액 — 압력·스퀴즈
8. A8 공매도 거래량/대금 — 하락 원인 분해
9. A2a 시가·종가 — 일봉 캔들 구조(상승 마감 비율 등)
10. A1a market/sector + A3C 주식수 — 유니버스 게이트·턴오버 정규화

### 2. 아직 없는 핵심 데이터 TOP 10
1. 1분봉 OHLCV(저장소 내 — 인프라는 완성)
2. 5분봉
3. tick/체결(체결시각·가격·수량·방향)
4. 호가 잔량(best bid/ask, 1~10단계)
5. 체결강도
6. 프로그램 매매(차익/비차익)
7. 시간대별 투자자 수급
8. 장중 누적 거래대금 궤적
9. opening range 원천(장 초반 분봉)
10. 장중 공매도 체결 추정치

### 3. 추가 확보 우선순위 TOP 3
1. **분봉 백필(T1) 즉시 가동** — 정책 MN-1.2·커넥터·프로브·배포 유닛까지 검증 완료 상태.
   KIS 보존이 ~1년(프로브 실측)이라 소급 불가 — 지연할수록 영구 손실 구간이 늘어나는
   유일한 항목. raw는 계약대로 오프사이트에 두고 manifest를 저장소에 커밋.
2. **체결강도/tick 대체 소스 스카우팅** — 초단기 모멘텀·imbalance 연구의 전제.
   분봉으로도 "분별 매수/매도 우위" 근사가 가능해지므로 분봉 확정 후 설계.
3. **호가 잔량 스냅샷 파일럿** — 소수 종목·제한 시간대라도 spread/imbalance 실측을
   시작해야 호가 기반 전략의 실현 가능성 판정이 가능.

---
검증 일시: 2026-08-22. 읽기 전용 감사 — 기존 파일 수정 0건, 수집/API 호출 없음.