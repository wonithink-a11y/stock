---
track: kr
factor: research-roadmap-after-regime-audit
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["P0-1 5DC-v1A-P Risk-Off 회피", "P0-2 VIX 인버스 ETN 정밀화", "P0-3 regime_labels×완료 전략 결합"]
reason: "Market Regime 감사 결과를 통합한 우선순위 로드맵 - '딱 하나 고르면' P0-1(5DC Risk-Off 회피) 선택, 전략 판정이 아닌 결정 대기 문서"
---
# 최종 연구 로드맵 — Market Regime 감사 이후 (2026-08-23)

1~7단계 감사 결과를 통합한 우선순위. 원칙: 기존 자산 최대 활용 → 소량 추가 데이터 →
인프라 구축 → 보류.

## P0 — 현재 데이터로 즉시 가능

### P0-1. 5DC-v1A-P Risk-Off 회피 검증
- 목적: regime_labels로 Risk-Off 회피 시 손익 분기 여부 확인(실측: Risk-On PF 2.13 /
  Risk-Off 0.24 / 전체 −71.5M원)
- 데이터: 5DC allTrades(보유) + regime_labels(보유) — 신규 없음
- 인프라: etp/regime 축 재사용, 기존 신호 정의 그대로
- 가치: ★★★(전략 생존성 판정을 바꾸는 단일 실험)
- 편향 위험: 라벨의 실시간 가용성(vixState는 D 종가 확정 → D+1 실행으로 이미 안전),
  11.5년 단일 시장
- 다음 명령: `reports/2026-08-23-regime-integration-suite` 스크립트에
  "Risk-Off 진입 스킵" 변형 1개 추가 후 재측정(신규 threshold 없음)

### P0-2. VIX 인버스 ETN overnight 전략 정밀화
- 목적: z≥+2 → 인버스(-0.5X) 진입, 다음날 시가 청산의 net +2.2bp(first-only)가
  강건한지 중앙값·월별·HIGH 유동성 컷으로 확인
- 데이터: data/etp/vix/(보유) + events.parquet(보유)
- 가치: ★★☆ / 위험: 클러스터링·단일 국면·비용 민감도
- 다음 명령: first-only + HIGH 컷 표를 vix-etn-regime-integration 보고서 형식으로 재집계

### P0-3. regime_labels × 완료 전략 국면 결합(E4 재도전)
- 목적: V3/V6 등 A등급 전략이 어느 국면에서 벌었는지/잃었는지
- 데이터: 기존 연구 스크립트 재실행(산출물은 새 경로에 저장해 기존 JSON 보존)
- 가치: ★★★(V6 +178bp의 국면 의존성이 승격 판단의 핵심)
- 편향 위험: 재실행 시 엔진 버전 drift(7e1bc61 이후) 주석 필수
- 다음 명령: 각 signal study에 --out-dir 옵션만 추가해 비파괴 재실행

## P1 — 소량 추가 데이터

### P1-1. S&P500 지수 백필
- 목적: VIX 급등 리바운드의 미국 동조성 검증(위성 vs 독립 분리)
- 데이터: FRED SP500(10년, fred() 재사용) + Stooq ^spx(장기 보조, 비공식)
- 가치: ★★★ / 편향: 없음(지수) / PIT: asOf 규칙 동일 적용 가능
- 다음 명령: build_sp500_backfill.py 신설(macro_common 재사용)

### P1-2. ETP 코드 마스터 확보
- 목적: survivorship 통제 universe(delisted 포함)
- 데이터: KRX 세션(KRX_ID/PW) 또는 finder 수집
- 가치: ★★★ / 위험: 무(메타데이터만)
- 다음 명령: CI 시크릿 유무 확인 → 세션 경로로 get_etf/etn_ticker_list 재검증

### P1-3. NDX100 지수 백필(FRED NASDAQ100)
- 성장주 국면 분리 필요 시점에 실행(Composite와 병기)

## P2 — 인프라 구축 필요

- ETP 전체 백필(P1-2 마스터 선행): 영역별 우선순위 순, 연도 청크 방식 재사용
- 거래대금/NAV 축(ISIN 조회 경로 — 로그인 세션 필요 확인됨)
- 연금 리밸런싱 백테스트 프레임(P0 결과에서 regime 조절 채택이 확인된 후)

## P3 — 현재는 보류

- 미국 breadth(전종목 인프라 필요)
- 미국 개별종목 수집
- VIX 선물지수/롤오버 정밀 데이터(유료 견적 대상)
- 장중 초단기 체결/호가 기반 전략(데이터축 부재)

---

## 최종 답변 (요구 7항)

1. **Market Regime 축은 충분한가?** — 예. features 44컬럼+labels(Risk-On/Off/Neutral)+
   매크로 12종(asOf provenance 포함)이 2016~2026-08-14 완비다. 결손은 S&P500/NDX100/
   미국 breadth뿐이고 이것은 확장 항목이다.
2. **어떤 전략부터 regime 분해하나?** — **5DC-v1A-P**(거래 테이블 보유, 분해 완료:
   Risk-On PF 2.13 vs Risk-Off 0.24). 다음은 산출물 비덮어쓰기 재실행으로 V3/V6.
3. **VIX ETN, 승격 전 필요 사항**: ①방향 정합(인버스 한정) 확인 상태에서 중앙값·
   월별 강건성 ②first-only HIGH 컷 ③시리즈 만기/롤오버 접합 규칙 문서화
   (metadata.parquet에 이미 구축돼 있음).
4. **S&P500/NASDAQ100 지금 추가해야 하나?** — **S&P500은 예(P1-1)**. FRED 무료,
   fred() 재사용, VIX 신호 검증의 기준축. NDX100은 Composite로 대체 중이라 직후 아님.
5. **미국 개별종목까지 지금?** — 아니요. breadth도 아직이며, 지수 축(S&P500)이 먼저고
   개별종목은 필요성 입증 후 별도 설계.
6. **연금/IRP 장기 리밸런싱 지금 시작 가능?** — **구조상 가능(조건부 B)**. 가격+PIT
   라벨 축 준비됨. 분배금 소스와 delisted 마스터가 남아 있으나 대형 지수 ETF 중심
   연구는 착수 가능하다.
7. **딱 하나 고르면**: **P0-1, "5DC-v1A-P Risk-Off 회피 검증"** — 데이터가 모두
   있고(신규 수집 0), Risk-Off −77.8M/Risk-On +47.6M라는 구조가 확인된 상태에서
   이 회피 규칙 하나가 전략의 생존성을 바꾸며, 통과 시 5DC의 엔진 통합 논의가
   완전히 달라진다.