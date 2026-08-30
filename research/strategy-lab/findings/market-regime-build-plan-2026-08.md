---
track: macro
factor: market-regime-build-plan
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["usd_krw_dexkus", "vix_vixcls", "regime_features_daily", "asOf_PIT"]
reason: "market-regime 최소 스키마·백필 설계 문서 - 9개 feature+PBR/VIX asOf 규칙 설계 후 실제 구축 완료(2026-08-23), KOSPI/KOSDAQ 지수는 소스 미확정으로 별도 트랙, 판정 없음"
---
# market-regime 데이터셋 구축 가능성 — 최소 스키마·백필 설계 (2026-08)

목적: market-regime 연구용 데이터셋을 **실제로 만들 수 있는지** 설계 수준에서
확정한다. 선행 문서 두 건을 이어받는다 — `findings/market-regime-readiness-2026-08.md`
(9개 feature 실행 검증 완료) · `findings/market-regime-data-source-check-2026-08.md`
(USD/KRW=`DEXKOUS`·VIX=`VIXCLS` 확정).

범위: research/strategy-lab/ 안에서만 작업. **설계 문서만 작성** — 실제 대량 수집·
코드 수정(기존 `scripts/fetch_macro.py` 등)·원본 데이터 변경·commit/push 없음.

---

## 0. 결론 요약

1. **9개 feature는 이미 실행으로 검증 끝났다**(readiness 문서) — A2a·A4·A1a·
   calendar.json만으로 2016-01~2026-08 전 구간 생성 가능, 신규 수집 불요.
2. **USD/KRW(`DEXKOUS`)·VIX(`VIXCLS`)는 `fetch_macro.py`의 `fred()` 함수를
   그대로 재사용**하면 소스 문제는 없다(source-check 문서) — 이번 문서는 그걸
   실제로 "어떻게 저장하고 어떻게 KR 거래일에 붙일지" 설계한다.
3. **KOSPI/KOSDAQ 지수**는 이번 두 후속 축(9개 feature·macro 2종)과 성격이
   다르다 — 소스 자체가 "확정 안 됨"(BF-1.1 §10 Actions 차단 vs calendar.json
   로컬 성공 전례가 충돌) 상태라 재실측이 먼저다. 이번 문서는 이 축을
   **스키마에 자리만 예약**하고 실제 설계는 하지 않는다(범위 밖 — 별도 조사 필요).
4. PIT의 핵심은 **타임존 격차**다: `DEXKOUS`/`VIXCLS`는 뉴욕 마감 기준 날짜가
   찍히는데, 그 날짜가 KST로 "알려지는" 시점은 다음날 새벽이다 — KR 거래일
   D에 안전하게 쓸 수 있는 값은 **"D보다 하루 이상 이전 날짜"로 찍힌 FRED
   관측치**뿐이다(§3).
5. 최소 스키마·백필 순서는 §4 — **바로 다음 세션이 실행할 수 있는 수준**으로
   구체화했다(단 실행은 이번 문서 범위 밖).

---

## 1. 9개 feature → 실제 원본 매핑

`readiness` 문서의 11항목 중 **이미 생성 가능 판정을 받은 9개**를,
`build_regime_feature_check.py`가 실제로 만든 컬럼과 대응시킨다(재확인 —
새로 실행하지 않음, 기존 산출 `regime_feature_coverage.json`을 그대로 인용).

| # | feature | 원본 데이터 | 스크립트 내 컬럼 | 계산식(요지) | 커버리지(2016-01~) |
|---|---|---|---|---|---|
| 1 | 시장 수익률 | A2a(수정주가 close) | `ew_ret` | 종목별 일간수익률의 동일가중 평균 | 2,595/2,604일(99.65%) |
| 2 | 20/60일 추세 | A2a(파생) | `trend20`, `trend60` | `ew_ret` 누적곱의 20/60거래일 전 대비 변화율 | 동일 |
| 3 | breadth | A2a(파생) | `adv_pct`, `above_ma20_pct`, `above_ma60_pct`, `nhnl_spread` | 상승종목비율·MA상회비율·250일 신고가-신저가 스프레드 | 동일 |
| 4 | realized volatility | A2a(파생) | `rvol10`, `rvol20`, `rvol60` | `ew_ret`의 10/20/60일 rolling 표준편차(ddof=1) | 동일 |
| 5 | 거래대금 | A4(`buyAmount.전체`) | `value_a4`, `value_z60` | 일별 전체 체결대금 합 + 60일 z-score | 2,604/2,604일(현행 유니버스 근사) |
| 6 | 외국인 수급 | A4(외국인+기타외국인) | `foreign_net_pct`, `foreign_net20_pct` | 순매수/당일거래대금, 20일 누적 순매수/20일 누적거래대금 | 동일 |
| 7 | 기관 수급 | A4(금융투자·보험·투신·사모·은행·기타금융·연기금 합산) | `inst_net_pct`, `inst_net20_pct` | 위와 동일 방식 | 동일 |
| 8 | cross-sectional dispersion | A2a(파생) | `xs_disp` | 횡단면 일간수익률 표준편차(ddof=1) | 2,595/2,604일 |
| 9 | 종목간 correlation | A2a(파생) | `impl_corr20` | 20일 개별 변동성·EW 변동성으로 역산한 implied 평균상관 | 동일 |

**추가 백필 대상(이번 문서가 다루는 것)**:

| 항목 | 원본(확정) | 현재 상태 | 이번 문서에서의 취급 |
|---|---|---|---|
| USD/KRW | FRED `DEXKOUS` | 미백필(소스만 확정) | §2·§3·§4에서 실제 설계 |
| VIX | FRED `VIXCLS` | 미백필(소스는 기존과 동일, 저장 방식만 문제) | §2·§3·§4에서 실제 설계 |
| KOSPI/KOSDAQ 지수 | **미확정**(pykrx 로컬 성공 vs Actions 차단 충돌, BF-1.1 §10) | 소스 자체 재실측 필요 | 스키마에 컬럼만 예약(§4), 설계는 범위 밖 |

---

## 2. `DEXKOUS`/`VIXCLS` 백필 방법 설계 (기존 코드 재사용, 무변경)

### 2-1. 재사용 대상 코드

`scripts/fetch_macro.py:31-47`의 `fred(series)` 함수 **그대로**:

```python
def fred(series):
    txt = http_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=" + series)
    out = []
    for line in txt.splitlines()[1:]:
        p = line.split(",")
        if len(p) < 2: continue
        d, v = p[0].strip(), p[-1].strip()
        if not v or v == ".": continue
        try: out.append((d, float(v)))
        except ValueError: continue
    return out
```

**원본은 수정하지 않는다.** research/strategy-lab 쪽에 이 함수를 **그대로 복사**해
쓰는 방식을 권한다(경로 hack으로 `scripts/`를 import하는 대신) — 이유는 CLAUDE.md의
Strategy Lab 격리 원칙과 같다: research/strategy-lab는 production 코드를 읽기
전용으로도 참조하지 않는 게 원칙이었다(A2a도 "읽기 전용"이지 "코드 import"는
아니었다). 15줄짜리 순수 함수라 복사 비용이 사실상 0이고, production
`fetch_macro.py`가 나중에 바뀌어도(예: UA 문자열 조정) research 쪽 재현성이
깨지지 않는다는 이점도 있다.

### 2-2. 저장 방식 — `weekly()`/`monthly()` 압축을 쓰지 않는다

운영 `fetch_macro.py`는 `weekly(obs, cap=80)`로 최근 80주만 남긴다(`docs/data/macro.json`용).
이건 **백필에 쓰면 안 된다** — 원본 문서(readiness §4)가 이미 "운영 롤링 파일은
역사 입력 금지"로 못박았다. `fred()`가 반환하는 리스트를 **압축 없이 그대로**
저장한다.

### 2-3. 제안 산출물 (설계만, 미생성)

```
research/strategy-lab/data/macro/
  dexkous_raw.parquet     # date(YYYY-MM-DD), value  — fred('DEXKOUS') 원본 그대로
  vixcls_raw.parquet      # date, value               — fred('VIXCLS') 원본 그대로
  macro_daily_kr.parquet  # KR 거래일 기준 asOf-join 결과 (§3 규칙 적용 후, 최종 소비용)
  _manifest.json          # 소스 URL·seriesId·조회시각·행수·기간 — BF-1.1 정식 manifest는
                           # 아니다(그건 data/backfill/ 전용, Actions만 쓸 권한 — 절대 규칙 4).
                           # research 쪽 재현성 기록용 경량 버전.
```

`research/strategy-lab/data/`는 이미 이 프로젝트의 선례가 있다(H6 스크립트가 쓰는
`data/a4/a4-research-dataset.parquet` 등) — production `data/backfill/`과 분리된
research 전용 캐시 관례를 그대로 따른다.

### 2-4. 실행 순서 (설계, 실행하지 않음)

1. `fred('DEXKOUS')`, `fred('VIXCLS')` 각 1회 호출 → `*_raw.parquet` 저장.
2. `data/backfill/calendar.json`의 `tradingDays`(KR 거래일)를 로드.
3. §3의 asOf 규칙으로 KR 거래일 D별 값을 backward-fill 방식으로 매핑
   (`pandas.merge_asof(direction='backward')`가 정확히 이 형태 — 정렬된 두
   시계열에서 "D 이전 가장 최근 관측치"를 자동으로 찾아준다. **KR 휴장일에만 있는
   FRED 잉여 관측치**(source-check 문서 §4-1에서 확인한 5건 사례)는 이 과정에서
   자연히 다음 KR 거래일의 후보로 흡수되므로 별도 예외처리가 불요하다).
4. `usdKrwLevel`(레벨)·`usdKrw20dChangePct`(20거래일 변화율, `fetch_macro.py`의
   `ago()`/`pct_change()`와 동일 공식) 파생.
5. `vixLevel`(레벨). 필요시 `vixPercentile1y`(1년 rolling percentile) 같은 파생은
   추후 실제 regime feature 설계 단계에서 결정 — 이번 문서는 원본 레벨 확보까지만
   설계 범위로 둔다.
6. `macro_daily_kr.parquet` + `_manifest.json` 저장.

---

## 3. PIT — KR 거래일 D에 쓸 macro 값의 as-of 날짜 규칙

### 3-1. 문제의 근원 — 타임존 격차

`DEXKOUS`(Fed H.10)·`VIXCLS`(CBOE 종가)는 **뉴욕 기준 날짜**가 관측치에 찍힌다.
그 날짜의 값이 실제로 "발표"되는 시각은 뉴욕 현지 마감 이후(대략 미 동부시각
오후)다. KST는 미 동부시각보다 13~14시간 빠르므로, **뉴욕 날짜 X로 찍힌 값은
KST로 "X+1일 새벽"에야 존재한다.**

예시(2026-08-14, 금요일 KR 거래일 기준으로 역산):

| FRED 날짜(뉴욕 기준) | 실제 발표 시각(추정, KST 환산) | KRX Aug-14 09:00 개장 전에 이미 나와 있었나 | KRX Aug-14 15:30 마감 전에 나와 있었나 |
|---|---|---|---|
| 2026-08-13(목) | Aug-14 새벽(약 03~04시 KST) | **예** | 예 |
| 2026-08-14(금) | Aug-15 새벽(약 03~04시 KST) | 아니오(당연히 미래) | **아니오** — Aug-14 장중엔 존재하지 않는 값 |

→ **KR 거래일 D의 마감(15:30 KST) 시점에 이미 알려져 있던 가장 최신 FRED
관측치는, 뉴욕 날짜 기준 "D-1(칼렌더 기준 전날)" 또는 그 이전이다.** 뉴욕
날짜 D 그 자체로 찍힌 값은 D의 KRX 마감 이후에도 아직 존재하지 않는다.

### 3-2. 채택 규칙

```
asOf_macro(D) = FRED 관측치 중 date < D 를 만족하는 가장 최근 값
              (= pandas merge_asof(..., direction='backward')로
                 "date < D" 경계를 강제한 것과 동일 — 등호(<=) 아님에 주의)
```

- 이건 프로젝트가 이미 PIT 원칙으로 쓰던 규약(readiness 문서 PIT 규칙 1:
  "t일 종가까지만 사용 → t+1 세션부터 사용")을 macro 축에 구체적으로 적용한
  것과 **동일한 결론**이다 — "D일 정보로 D+1부터 쓴다"는 이미 있던 원칙이,
  FRED의 타임존 격차 때문에 **뉴욕 날짜 기준으로는 한 칸 더 밀려야** 정확히
  맞아떨어진다는 걸 이번에 구체화했을 뿐이다.
- 주말·공휴일 처리는 별도 로직이 필요 없다 — `merge_asof(direction='backward')`가
  "D 이전 가장 최근 값"을 자동으로 찾으므로, 연휴로 며칠 비어 있어도 자연스럽게
  그 이전 마지막 관측치가 이어진다.
- **미확인 잔여 리스크**: 위 "약 13~14시간, 발표 시각 오후" 추정은 Fed H.10·CBOE의
  일반적 공개 관행에서 유도한 것이지, 이번 조사에서 실제 발표 타임스탬프를
  직접 관측하진 않았다(FRED 그래프 CSV는 발표 시각을 안 준다). **`date < D`
  규칙은 이 추정이 어긋나도 안전한 쪽으로 여유가 있다** — 발표가 예상보다
  늦어도 최소 하루 통짜 여유가 있으므로 보수적으로 안전하다. 반대로 더 타이트한
  규칙(예: 당일 뉴욕 날짜를 그대로 쓰는 것)은 이번 조사로 **명확히 위험하다고
  판정**한다.

### 3-3. 기존 규칙과의 정합성 재확인

- readiness 문서 PIT 규칙과 상충하지 않는다 — 오히려 그 규칙이 이미 "운영 롤링
  파일(현재값 스냅샷)은 역사 입력 금지"라고 했던 것과 같은 정신이다: **"지금 그
  값을 볼 수 있다"와 "그 시점에 그 값이 존재했다"를 구분**하는 문제다.
- A4(수급) 데이터의 "장마감 확정치, 장중 사용 금지"(readiness 문서 PIT 규칙 5)와
  같은 계열의 문제이지만, macro는 **정보가 다음날 KST 새벽에 이미 나와 있다**는
  점에서 A4보다는 오히려 여유가 있다(A4는 그날 마감돼야 나오는데, macro D-1값은
  D 개장 전에 이미 확보돼 있다).

---

## 4. 최소 데이터 스키마 + 백필 작업 순서 제안

### 4-1. 최소 스키마 (제안, 미생성)

파일: `research/strategy-lab/data/macro/regime_features_daily.parquet`
(1행 = 1 KR 거래일, key=`date`)

| 컬럼 | 출처 | 비고 |
|---|---|---|
| `date` | calendar.json tradingDays | KR 거래일, PK |
| `ew_ret`, `trend20`, `trend60` | A2a 파생(§1 #1-2) | 이미 검증 완료 |
| `adv_pct`, `above_ma20_pct`, `above_ma60_pct`, `nhnl_spread` | A2a 파생(§1 #3) | 〃 |
| `rvol10`, `rvol20`, `rvol60` | A2a 파생(§1 #4) | 〃 |
| `value_a4`, `value_z60` | A4 파생(§1 #5) | 〃 |
| `foreign_net_pct`, `foreign_net20_pct` | A4 파생(§1 #6) | 〃 |
| `inst_net_pct`, `inst_net20_pct` | A4 파생(§1 #7) | 〃 |
| `xs_disp` | A2a 파생(§1 #8) | 〃 |
| `impl_corr20` | A2a 파생(§1 #9) | 〃 |
| `usdKrwLevel`, `usdKrw20dChangePct` | FRED `DEXKOUS`(§2·§3 asOf 적용) | **신규** |
| `usdKrwAsOfDate` | 〃 | 실제 사용된 FRED 관측일(뉴욕 날짜) — 감사용 provenance, 절대 규칙 1과 같은 정신: "언제 값인지 숨기지 않는다" |
| `vixLevel` | FRED `VIXCLS`(§2·§3 asOf 적용) | **신규** |
| `vixAsOfDate` | 〃 | 〃 |
| `kospiClose`, `kosdaqClose` (+ 파생 예정 trend·거래대금) | **미확정** | 컬럼만 예약, 전부 null. 소스 재실측 전까지 절대 규칙 1대로 결측 그대로 둔다(기본값 채우지 않음) |

### 4-2. 백필 작업 순서 제안 (실행은 범위 밖, 순서만 제안)

```
1순위  USD/KRW(DEXKOUS) 백필
       — 가장 간단(신규 코드 없음), marketRegimeEngine 백테스트 검증의
         선결 조건(인벤토리 문서가 이미 최우선으로 지목)
2순위  VIX(VIXCLS) + 같이 쓰던 나머지 FRED 계열(T10Y2Y·BAMLH0A0HYM2·M2SL·
       DTWEXBGS) 동시 백필
       — DEXKOUS와 같은 fred() 호출 패턴이라 한 번에 묶는 게 비용 최소.
         이미 fetch_macro.py가 다루는 지표라 "새 지표 조사" 비용이 없다
3순위  9개 feature를 build_regime_feature_check.py 방식 그대로
       regime_features_daily.parquet로 "승격"(검증용 JSON 샘플이 아니라
       실제 전 구간 저장) — 이미 로직 검증 끝났으므로 순서상 급하지 않음,
       1·2순위와 병렬 진행 가능
4순위  KOSPI/KOSDAQ 지수 — **별도 트랙**. 착수 전에 BF-1.1 §10(Actions 차단)과
       calendar.json 로컬 성공 전례의 충돌부터 재실측해야 한다(readiness
       문서·인벤토리 문서 공통 결론). 이번 설계 문서의 스키마는 컬럼만
       비워 두고 진행 순서에서는 독립적으로 취급
```

**왜 이 순서인가**: 1·2순위는 이미 "무엇을(source-check 문서)"과 "어떻게(§2·§3)"가
모두 끝나 **다음 세션이 바로 실행 설계로 넘어갈 수 있는 상태**다. 3순위는 이미
readiness 문서가 실행 검증까지 마쳤으니 "승격" 작업일 뿐 리스크가 없다. 4순위만
소스 자체의 불확실성이 남아 있어 별도 조사 세션이 필요하다 — 나머지 순서를
기다리게 할 이유가 없다.

---

## 5. ★ 실제 구축 완료 (2026-08-23, 사용자 GO)

설계(§1-4)를 실제로 실행했다. 스크립트: `build_usdkrw_backfill.py` ·
`build_vix_backfill.py`(공통 `macro_common.py`) · `build_regime_features_backfill.py`
(9개 feature — `reports/2026-08-23-market-regime-readiness/build_regime_feature_check.py`
의 계산식을 그대로 이식, 원본 무변경). 전부 `research/strategy-lab/data/market-regime/`.

**quality audit (`--audit`)**: 9개 feature 전부 readiness 문서의
`regime_feature_coverage.json`과 validDays **완전 일치**(9/9) + **128개 월간
샘플 값 직접 대조 불일치 0건** — 계산식 이식 과정에서 숫자가 하나도
바뀌지 않았음을 확인. selftest 3개 스크립트 전부 통과(6/6·4/4·5/5).

**산출물**: 9개 feature 그룹 parquet(각 `_manifest_<group>.json`: 원천·계산식
원출처·PIT 규칙·coverage·중복여부·생성 commit 포함) + `usdkrw_daily_kr.parquet`·
`vix_daily_kr.parquet` + 통합 `market_regime_features.parquet`(2,604행×25컬럼,
2016-01-04~2026-08-14, 중복 date 0건).

**PIT 설계 조정 1건**: macro(USD/KRW·VIX)는 뉴욕 날짜 기준이라 지연폭이
날마다 달라 `AsOfDate` 컬럼(실제 쓰인 FRED 관측일)이 필요했다. 9개
feature는 전부 같은 날 A2a/A4 마감확정치라 그런 조회가 필요 없어, 대신
`usableFromDate`(=date+1 거래일)로 PIT 감사 가능성을 확보했다 — 마지막
행(2026-08-14)은 다음 거래일이 아직 없어 `None`으로 정직하게 비워둔다.

**부수 발견**: 이식 중 `DEXKOUS`가 결측을 `.` 외에 완전 빈 문자열로도
표기한다는 사실을 새로 확인(미국 공휴일, 2014년 이후 139건) —
`market-regime-data-source-check-2026-08.md`의 "결측 0건" 서술을 정정.
`fred()`의 `if not v` 필터는 이미 정상 동작해 코드 버그는 아니었음.

**범위 밖으로 남긴 것**: KOSPI/KOSDAQ 지수(소스 자체 미확정, 별도 재실측
필요) — 나머지 9개 feature+macro 산출물의 완료와 독립적으로 취급.

---

## 검증 가능한 근거 목록

- `research/strategy-lab/findings/market-regime-readiness-2026-08.md` — 9개 feature
  실행 검증 판정표·PIT 규칙 원본
- `research/strategy-lab/reports/2026-08-23-market-regime-readiness/
  build_regime_feature_check.py` — 실제 컬럼명·계산식 확인(§1 표의 원출처)
- `research/strategy-lab/findings/market-regime-data-source-check-2026-08.md` —
  `DEXKOUS`/`VIXCLS` series 확정, KR 거래일 대비 결측 0건 실측(§4-1의 근거)
- `scripts/fetch_macro.py:31-47`(`fred()`) — 무변경 재사용 대상, 원문 인용(§2-1)
- `data/backfill/calendar.json` — KR 거래일 소스(§4-1 asOf 조인의 기준)
- `docs/BF-1.1-백필계약.md` §10 — KOSPI/KOSDAQ 지수 Actions 차단 기록(§4-2
  4순위 보류 사유)
