---
track: macro
factor: market-regime-final-data-inventory
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "Market Regime 데이터축 최종 인벤토리 - features 44컬럼·regime labels 2,604일 구축 확정, 결손은 S&P500·NASDAQ-100·KOSPI 공식지수 뿐"
---
# Market Regime 데이터축 최종 인벤토리 감사 (2026-08-23)

목적: research/strategy-lab에 존재하는 시장/매크로 데이터 전체를 실측 조사해
Market Regime 연구축 통합 가능성을 최종 판정한다.
방법: data/** parquet/json 전수 스캔(pyarrow 메타데이터+값 결측률 실측) +
      market-regime 문서군 교차. 읽기 전용, 수정·수집 없음.
산출물: reports/2026-08-23-market-regime-final-inventory/{inventory_scan.py,
inventory_result.json}

## 0. 총평 — 축이 이미 구축돼 있었다

병렬 세션의 작업으로 `research/strategy-lab/data/market-regime/`에 **정식 feature
파일(market_regime_features.parquet, 44컬럼)과 regime 라벨(regime_labels.parquet)까지
완성된 상태**였다. 모든 값 컬럼의 결측률은 최대 1.5%(워밍업 구간)로 사실상 완결이다.
또한 data/etp/vix/(VIX ETN 일봉·이벤트 테이블)도 병렬 구축돼 있었다.
본 감사는 이 축의 존재와 내용을 독립적으로 실측해 확정한다.

## 1. 데이터셋별 인벤토리

### 1-1. USD/KRW
| 항목 | 값 |
|---|---|
| 파일 | data/market-regime/usdkrw_daily_kr.parquet (+dexkous_raw.parquet FRED 원본) |
| 기간/빈도 | daily KR 거래일(asOf join) |
| 관측치 | usdkrw_daily_kr: usdKrwLevel 결측 0/3,097 |
| raw | dexkous_raw 1981-04-13~2026-08-14, 11,333행, 결측 0 |
| PIT/asOf | date<D backward(build-plan §3-2), AsOfDate provenance 포함 |
| 생존편향 | 없음(단일 시계열) |
| 사용가능/추가작업 | 즉시 사용 가능 / 없음 |

### 1-2. VIX
| 항목 | 값 |
|---|---|
| 파일 | vix_daily_kr.parquet(3,097행, 2014-01-02~2026-08-14) · vixcls_raw.parquet(1990-01-02~2026-08-20, 9,256행) |
| 결측률 | vixLevel 0% |
| PIT/asOf | 동일 규칙 적용 완료(vixLevelAsOfDate 포함) |
| 사용가능/추가작업 | 즉시 사용 가능 / 없음 |

### 1-3. VIX ETN 축 (data/etp/)
| 파일 | rows | 범위 | 비고 |
|---|---|---|---|
| etp/vix/daily_prices.parquet | 3,203 | 2022-09-16~2026-08-21 | VIX ETN 4종 통합 일봉(OHLCV 결측 0) |
| etp/vix/events.parquet | 129 | 2024-08-05~2026-03-31 | z신호×ETN 이벤트 테이블(T+1/5/10/20 close·nextopen, inverse 78/false 46) — 병렬 세션이 신호×ETN 이벤트 스터디까지 구축한 상태 |
| etp/vix/metadata.parquet | 9행 | - | issuer/type/underlying_index/leverage/inverse/currency_exposure/maturity/delisting/status(+evidence)/first_trade/last_trade — **코드 마스터+상폐일이 이미 구축됨**(survivorship 통제 전제 충족) |
| etp/prices/{4 codes}.parquet | 각 375~721 | 개별 일봉 | 본 세션 이전 실측분 |

### 1-4. Market Regime 파생 변수 파일 (전부 2016-01-04~2026-08-14, 2,604행)

| 파일 | 주요 컬럼 | 결측률 |
|---|---|---|
| market_return.parquet | ew_ret | 0.35% |
| trend.parquet | trend20, trend60 | 0.35% |
| breadth.parquet | adv_pct, above_ma20_pct, above_ma60_pct | 0.35% |
| realized_vol.parquet | rvol10/20/60 | 0.35% |
| turnover_value.parquet | value_a4(A4 거래대금), value_z60 | 0%/1.50%(z 워밍업) |
| foreign_flow.parquet | foreign_net_pct, foreign_net20_pct | 0% |
| institution_flow.parquet | inst_net_pct, inst_net20_pct | 0% |
| dispersion.parquet | xs_disp | 0.35% |
| correlation.parquet | impl_corr20 | 0.35% |

### 1-5. 통합 피처/라벨
| 파일 | 내용 |
|---|---|
| market_regime_features.parquet | **44컬럼**: §A~F 전부 + 매크로(usdKrw/vix/usFedFunds/usTreasury10y/usNasdaq/krKospi/krTreasury3y/krCorpAA3y/krCpi/krLeadingCyclical/krCoincidentCyclical/krCreditSpreadBp) + **각각 AsOfDate provenance** |
| regime_labels.parquet | vixState(Low/Mid/High)·trendState·breadthState·fxState·riskScore·**regime(Risk-On 826/Risk-Off 297/Neutral 1,472)** + usableFromDate(PIT) |

### 1-6. A4 (유동성·수급)
a4-research-dataset.parquet: **5,348,454행 × 35컬럼**, total_amount/total_volume/
foreign_nb_1d·5d·20d/inst_nb_*/indiv_nb_* 등 수급·거래대금 컬럼 보유.
품질은 동 디렉터리 a4-data-quality.json 참조(청산 항등식 재검증 완료본).

### 1-7. 금리
| 데이터 | 파일 | 범위 | rows | 결측 |
|---|---|---|---|---|
| US 10Y | ustreasury10y_raw.parquet | 1962-01-02~2026-08-20 | 16,144 | 0 |
| Fed Funds | usfedfundsrate_raw.parquet | 1954-07-01~2026-08-20 | 26,349 | 0 |
| KR 국고채 3Y | krtreasury3y_raw.parquet | 2014-01-02~2026-08-21 | 3,113 | 0 |
| KR 회사채 AA− 3Y | krcorpaa3y_raw.parquet | 2014-01-02~2026-08-21 | 3,113 | 0 |
| Yield curve(운영) | docs/data/macro.json indicators.yieldcurve | 롤링 최근분 | - | 운영 스냅샷(역사 백필 아님) |

raw 단계라 KR 거래일 asOf 정규화는 미적용(레이어 결합 시 §3-2 규칙 적용 필요).

### 1-8. 한국 거시
krcpi_raw(월별 151건, 2014-02~2026-08) · krleadingcyclical/krcoincidentcyclical
(주간 150건, 2014-04~2026-08-29) · krkospi_raw(**3,000행 컷**, 2014-05-30~2026-08-21 —
KRX 개별경로 행수 제한 상속, 전체 이력은 추가 분할 수집 과제).

### 1-9. 미국시장
| 항목 | 결과 |
|---|---|
| NASDAQ | **있음** — usnasdaq_raw.parquet(1971-02-05~2026-08-21, 14,004행, NASDAQ **Composite**) + macro_layer/features에 usNasdaq asOf 반영 완료 |
| S&P 500 | **없음**(저장소 어디에도 없음을 재확인) |
| NASDAQ-100 | **없음**(Composite만 존재 — 명확히 구분 기록) |
| 미국 breadth/volatility | 없음(자체 산출 불가 — 미국 종목 유니버스 부재) |

## 2. Market Regime Feature Set 확정

| 그룹 | feature | 판정 |
|---|---|---|
| A Trend | market return(ew_ret), trend20, trend60 | **이미 생성됨** |
| B Breadth | %above MA20/MA60(+adv_pct, nhnl_spread) | **이미 생성됨** |
| C Volatility | rvol10/20/60 + VIX(z-state까지 labels에 반영) | **이미 생성됨** |
| D Liquidity | turnover_value(value_a4, value_z60) | **이미 생성됨** |
| E Flow | foreign/institution net_pct, net20_pct | **이미 생성됨** |
| F Cross-sectional | xs_disp, impl_corr20 | **이미 생성됨** |
| G Macro | USD/KRW(level+20d change), US 10Y, FedFunds, NASDAQ, KR 금리·CPI·선행/동행·신용스프레드 | **이미 생성됨** (S&P500/NASDAQ100/미국 breadth만 데이터 부족) |

## 3. 질문 응답

1. **한국시장 regime 연구를 바로 시작할 수 있는가?** — **예.** features(44컬럼)+
   labels(Risk-On/Off/Neutral)가 PIT provenance 포함 2,604일치로 이미 존재한다.
   남은 것은 이 축과 기존 전략 이벤트의 결합 분석뿐이다.
2. **중복 feature는?** — ew_ret/trend/rvol/breadth/flow 등이 개별 parquet과
   market_regime_features 양쪽에 이중 저장(동일 값, 파일 분할 뷰 관계).
   VIX 레벨은 vix_daily_kr·macro_layer·features 3곳에 중복 — 소스 단일성은 유지되므로
   문제는 아니나 정규 참조 위치 지정 권장.
3. **가장 중요한 결손 데이터는?** — ①S&P500 지수(미국 시장 검증의 기준축) ②NASDAQ-100
   (Composite만 보유) ③KOSPI/KOSDAQ 공식 지수(현재 krkospi_raw가 3,000행 컷) 
   ④ETP 분배금 ⑤미국 breadth.
4. **S&P500/NASDAQ100 추가 시 연구력 증가?** — 크다. ①VIX 신호의 원 체장(S&P)
   동조성 검증으로 "한국 리바운드가 미국 회복의 위성인지" 분리 가능 ②나스닥100은
   KOSDAQ 성격 비교 축 ③macro_layer의 usNasdaq(Composite)과 결합하면 미국 국면
   정의 자체를 미국 데이터로 할 수 있다. 현재는 한국 EW 단일 추정이라 인과 해석이
   약하다.
5. **수집보다 먼저 할 연구는?** — **존재하는 regime_labels × 기존 전략(V1~V8, 3B,
   minute 패턴) 성과 국면 분해.** 라벨·피처·전략 결과가 모두 있는데 결합만 안 된
   상태다. 이 결합 결과가 나와야 다음 데이터 투자(S&P500 등)의 우선순위가 정해진다.

## 부기
- data/macro → data/market-regime 디렉터 리네임은 타 세션 작업이며, 본 감사는
  이동 후 위치를 기준으로 실측했다.
- VIXCLS 현물 ≠ 선물/ETN 구조 차이는 vix-etn-validation 문서의 기술을 그대로 상속한다.
