---
title: Findings 분류 체계
date: 2026-08-31
total_files: 242
---

# Findings Classification

> `_classification.jsonl`에 분류된 242개 마크다운 파일의 구조 요약.
> 이 문서는 `RESEARCH-FINDINGS.md`(종합 연구 로그)와 `_registry.jsonl`(단일 파일 메타)를 보완하는 **주제·단계별 분류 인덱스**다.

## 트랙 분포

| Track | Count | 비중 |
|-------|------:|-----:|
| kr    | 172   | 71%  |
| crypto| 41    | 17%  |
| macro | 24    | 10%  |
| us    | 4     | 2%   |
| xasset| 1     | <1%  |

## 카테고리 분포

### KR (172건)

| Category | Count | 설명 |
|----------|------:|------|
| kr_factor | 62 | 팩터 스캐닝·견고성·증분 검증 |
| kr_strategy | 45 | 전략 백테스트·검증·기각 |
| kr_intraday | 25 | 장중 전략·분봉 데이터·인트라데이 |
| kr_chart_tech | 25 | 차트 기법 탐색·신호 스터디 |
| kr_data_audit | 8 | 데이터 필드·소스·인프라 감사 |

### KR Factor 하위 (주요)

| Sub-category | Count | 예시 |
|-------------|------:|------|
| pbr | 15 | kr-pbr-robustness, pbr-combined-*, pbr-dropout-* |
| composite_verification | 12 | factor-composite, factor-discovery-kr, factor-robustness-kr |
| flow_basic | 9 | flow-basic-effect, flow-acceleration, flow-price-confirmation-* |
| earnings_yield | 7 | factor-earnings-yield-* |
| fundamental_scan | 6 | kr-fundamental-scan, kr-fundamental-quality-value |
| foreign_flow | 4 | kr-foreign-flow-* |

### KR Strategy 하위 (주요)

| Sub-category | Count | 예시 |
|-------------|------:|------|
| cand1 | 9 | cand1-* |
| opening_fade | 4 | opening-fade-* |
| 5dc | 5 | 5dc-riskoff-*, 5dc-v1a-p-* |
| pbr | (strategy) | pbr-ratefilter, pbr-max-exclusion |
| dd252 | 4 | dd252-* |
| lowmom60 | 3 | lowmom60-* |
| trend_breakout | 3 | trend-breakout-*, trendbreakout-* |

### KR Intraday 하위

| Sub-category | Count | 예시 |
|-------------|------:|------|
| opening_fade_sub | 10 | minute-opening-fade-cost, -exlimits, -monthly, -window |
| minute_fade | 3 | minute-fade-net-costs, minute-fade-regime |
| intraday_data | 6 | intraday-data-inventory, minute-data-quality |
| intraday_chart | 5 | intraday-chart-research, intraday-timeofday |

### KR Chart Tech 하위

| Sub-category | Count | 예시 |
|-------------|------:|------|
| bollinger_rsi | 5 | v3-bb-rsi, v3-engine-smoke, v3-overlap-check |
| accrual_price | 5 | v6-accrual-price, v6-liquidity-check |
| divergence | 4 | v5-divergence, v5b-expension |
| support_resistance | 3 | support-resistance, v4-fib-sr |

### Crypto (41건)

| Category | Count | 설명 |
|----------|------:|------|
| crypto_strategy | 14 | 커뮤니티 전략 백테스트·워크포워드 |
| crypto_signal | 12 | 이벤트 독립성·신호 견고성 |
| crypto_microstructure | 9 | 펀딩·프리미엄·taker ratio·주문 흐름 |
| crypto_data_audit | 6 | 데이터 소스·인프라 감사 |

### Macro (24건)

| Category | Count | 설명 |
|----------|------:|------|
| macro_regime | 11 | 시장 국면 정의·분류·백필 |
| macro_vix | 9 | VIX·변동성 전략·분석 |
| macro_data | 4 | 매크로 데이터 소스·인프라 |
| macro_synthesis | 1 | 다중 전략×국면 교차 종합 |

### US / XAsset / Meta

| Category | Count | 설명 |
|----------|------:|------|
| us_strategy | 2 | 미국 시장 전략 검증 |
| us_data_audit | 2 | 미국 시장 데이터 소스 조사 |
| xasset_regime | 1 | 교차 자산 국면 감사 |
| meta | 6 | 레지스트리·종합 문서·로드맵 |

## 단계(Stage) 분포

| Stage | Count | 설명 |
|-------|------:|------|
| exploration | 77 | 초기 탐색·데이터 감사·방향성 확인 |
| validation | 64 | 견고성 검증·OOS·엔진 연결 |
| signal_study | 42 | 신호 첫 실행·이벤트 스터디 |
| rejection | 34 | 최종 기각 |
| portfolio_test | 16 | 포트폴리오 수준 백테스트·비용 반영 |
| meta | 9 | 문서·요약·로드맵 |

## 파일 구조

```
_classification.jsonl   ← 242줄, 줄당 1 JSON 객체
RESEARCH-FINDINGS.md    ← 종합 연구 로그 (누적)
_registry.jsonl          ← 단일 파일 메타데이터 (verdict 등)
```

## 사용법

`_classification.jsonl`에서 특정 카테고리/단계별로 필터링:

```bash
# KR Factor 연구 중 rejection 단계
grep '"category": "kr_factor"' _classification.jsonl | grep '"stage": "rejection"'

# 크립토 전략 관련 전체
grep '"category": "crypto_strategy"' _classification.jsonl

# macro regime 관련 전체
grep '"category": "macro_regime"' _classification.jsonl
```
