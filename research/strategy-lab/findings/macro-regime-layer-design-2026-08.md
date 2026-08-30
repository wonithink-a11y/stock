---
track: macro
factor: macro-regime-layer-design
date: 2026-08-23
verdict: UNCLASSIFIED
criteria_version: backfill-v1
reason: "Macro Regime Layer(10축) 스키마·PIT·정합 규칙 설계 + synthetic selftest 12/12 PASS - CPI/경기지수 lag 상수는 보수적 추정, 실제 백필은 범위 밖"
---
# Macro Regime Layer — schema·PIT·정합 규칙 설계 (2026-08)

목적: `macro-regime-layer-data-source-check-2026-08.md`(§7까지, 소스 확정)를 이어받아
**실제 백필 전** 스키마·PIT·정합 규칙을 확정한다. 사용자 지시(2026-08-23) 10항목을
그대로 따른다. **실제 백필 실행은 이 문서 범위 밖 — 여기서 중단한다.**

범위: research/strategy-lab/ 안에서만 작업. 코드는 synthetic selftest 스크립트
하나만 신규 작성(§9), 실제 데이터 수집·parquet 생성 없음. commit/push 없음(선행
문서들과 같은 관례).

---

## 1. 확정된 데이터 — 9개 raw + 1개 derived = 10

| # | 이름 | 소스 | series/item code | 빈도 |
|---|---|---|---|---|
| 1 | `usFedFundsRate` | FRED | `DFF` | 일별 |
| 2 | `usTreasury10y` | FRED | `DGS10` | 일별 |
| 3 | `usNasdaq` | FRED | `NASDAQCOM` | 일별 |
| 4 | `krKospi` | 네이버 차트(`fetchDailyCandlesKR` 패턴, count 확장) | `KOSPI` | 일별 |
| 5 | `krTreasury3y` | ECOS | `817Y002`/`010200000` | 일별 |
| 6 | `krCorpAA3y` | ECOS | `817Y002`/`010300000` | 일별 |
| 7 | `krCpi` | ECOS | `901Y009`/`0` | **월별** |
| 8 | `krLeadingCyclical` | ECOS | `901Y067`/`I16E` | **월별** |
| 9 | `krCoincidentCyclical` | ECOS | `901Y067`/`I16D` | **월별** |
| 10 | `krCreditSpreadBp` | **derived** = (`krCorpAA3y` − `krTreasury3y`) × 100 | — | 일별(6·5의 파생) |

기존 `market_regime_features.parquet`의 `usdKrwLevel`·`vixLevel`은 이미 있으므로
재수집하지 않는다 — 이 10개만 신규.

---

## 2. 일별/월별 혼합 규칙

**새 조인 로직을 만들지 않는다.** 기존 `macro_common.py::asof_join_kr()`이 이미
"KR 거래일 D에는 `date < D`인 가장 최근 관측치만 쓴다"는 걸 구현해뒀다(FRED
daily 전용으로 설계됐지만 요구하는 건 `[(date, value), ...]` 리스트뿐 — FRED인지
ECOS인지 모른다).

**해법**: 월별 시리즈(`krCpi`·`krLeadingCyclical`·`krCoincidentCyclical`)를
`asof_join_kr()`에 넣기 전에, 각 관측치의 "참조월"을 그대로 넣지 않고 **§3에서
정의하는 `usableFromDate`로 이미 바꿔서** 넣는다. 그러면 `asof_join_kr()`은 일별·
월별을 구분할 필요가 없다 — "언제부터 알 수 있었나"라는 같은 질문에 이미 답한
날짜만 받기 때문이다. 새 파라미터·새 브랜치 불요, 입력 전처리 한 단계만 추가.

---

## 3. Publication Date 기반 PIT 규칙

### 3.1 일별 시리즈(1~6번)

기존 USD/KRW·VIX와 같은 규칙 그대로: 관측일자 자체가 `usableFromDate`다.
`asof_join_kr()`의 `allow_exact_matches=False`(등호 배제)가 "그날 마감가는 그날
아직 못 쓴다"를 이미 강제한다 — 추가 규칙 불요.

### 3.2 월별 시리즈(7~9번) — 실제 발표 관행 확인 (2026-08-23 웹검색)

ECOS API는 발표일 필드를 안 준다(관측월만 온다) — **발표 관행을 별도로 확인해야
`usableFromDate`를 만들 수 있다.** 웹검색으로 확인(출처는 문서 끝 참고):

- **CPI(`krCpi`)**: 통계청 소비자물가동향은 **매월 초(익월 2~5일 무렵)** 발표.
  정확한 "며칠"까지는 이번 조사로 확정 못 했다(공식 캘린더 페이지 직접 확인
  필요) — **보수적으로 참조월 말일 + 5일**을 `usableFromDate`로 잡는다. 실제
  발표가 이보다 이르면(예: 익월 2일) 이 규칙은 실제보다 최대 며칠 늦게 데이터를
  "사용 가능"으로 처리하는 셈이다 — **미래참조보다 항상 안전한 방향의 오차**라
  의도적으로 이렇게 정한다.
- **경기종합지수(`krLeadingCyclical`·`krCoincidentCyclical`)**: 통계청 산업활동동향은
  **익월 하순(대략 참조월 말일+30~40일)** 발표하되, **12월분은 예외적으로 다음해
  2월 상순(참조월 말일+60일 이상)**에 나온다(연말 통계 정정 때문으로 추정,
  원인은 조사 범위 밖). 월별로 다른 lag를 계산하는 대신 **모든 달에 균일하게
  "참조월 말일 + 60일"을 적용**한다 — 12월 예외까지 한 규칙으로 덮으면서도
  일반 달엔 최대 20일 정도 더 보수적일 뿐이다(안전한 방향, ponytail: 월별 예외
  분기 대신 단일 상수로 단순화 — 나중에 실제 발표일 데이터를 확보하면 월별
  정밀화로 올릴 수 있다).

이 두 lag 상수(CPI=5일, 경기종합지수=60일)는 **실제 발표일 원자료로 확정된 게
아니라 웹검색 기반 보수적 추정**이다 — 실제 백필 전에 통계청 공표일정
페이지(`kostat.go.kr`)나 과거 보도자료 날짜를 직접 대조해 재확인하는 게
안전하다(§10에 남김).

### 3.3 usableFromDate 계산식 정리

```
일별(1~6, 10번)   usableFromDate = 관측일자 그 자체
                  (asof_join_kr의 등호배제가 "다음날부터"를 보장)
CPI(7)            usableFromDate = 참조월 말일 + 5일(달력일)
경기종합지수(8·9)  usableFromDate = 참조월 말일 + 60일(달력일, 12월 예외 포함)
```

---

## 4. 한국 거래일 alignment 규칙

기존 규칙 재사용 — `data/backfill/calendar.json`의 `tradingDays`만 정본으로 쓴다
(§ macro_common.py, MN-1.0의 calendar 동결 원칙과 동일). 새 캘린더·새 로직 불요.
일별 시리즈는 이미 `merge_asof(direction="backward")`가 미국 공휴일·주말 갭을
KR 거래일 기준으로 자연 처리한다(§ 기존 selftest "주말 갭도 backward-fill로 자연
처리된다" 항목, macro_common.py:119-121). 월별 시리즈도 `usableFromDate`를 계산해
넣기만 하면 같은 로직이 그대로 먹는다.

---

## 5. 결측 처리 규칙

절대 규칙 1("결측에 기본점수 금지") 그대로:

- API 호출 자체가 실패하거나 특정 구간에 값이 없으면 **해당 KR 거래일의 그
  컬럼은 `NaN`** — 보간·전진채움으로 지어내지 않는다. (주의: 이건 "월별 값을
  다음 발표까지 유지"하는 §2의 forward-fill과는 다른 층위다 — forward-fill은
  "이미 발표된 값을 다음 발표 전까지 그대로 쓴다"는 정상 PIT 동작이고, 결측
  처리는 "애초에 발표된 값 자체가 없거나 못 받아온 경우"다. 헷갈리지 않게
  구분해 구현한다.)
- `asof_join_kr()`이 이미 이 성질을 갖고 있다(기존 selftest "FRED 이력 이전
  날짜는 NaN" 항목) — 그대로 상속.
- 신규 파생값(`krCreditSpreadBp`)은 두 입력(`krCorpAA3y`·`krTreasury3y`) 중
  하나라도 NaN이면 결과도 NaN — 지어내지 않는다.

---

## 6. usableFromDate 생성 규칙 — §3.3과 동일, 소스 컬럼 매핑만 별도 표

| 데이터 | 원본 날짜 컬럼 | usableFromDate 계산 |
|---|---|---|
| usFedFundsRate·usTreasury10y·usNasdaq | FRED observation_date | = 그 날짜 |
| krKospi | 네이버 캔들 date | = 그 날짜 |
| krTreasury3y·krCorpAA3y | ECOS `TIME`(YYYYMMDD, 일별) | = 그 날짜 |
| krCpi | ECOS `TIME`(YYYYMM, 월별) | = 참조월 말일 + 5일 |
| krLeadingCyclical·krCoincidentCyclical | ECOS `TIME`(YYYYMM, 월별) | = 참조월 말일 + 60일 |
| krCreditSpreadBp(파생) | — | = max(krCorpAA3y usableFromDate, krTreasury3y usableFromDate) |

---

## 7. `macro_regime_features.parquet` 확장 스키마

기존 `data/market-regime/market_regime_features.parquet`(2,604행×25컬럼, `date`
인덱스)에 컬럼만 추가한다 — **별도 파일을 만들지 않는다**(§8과 같은 이유,
join 비용·정합성 관리 지점을 하나로 유지).

기존 관례(`usdKrwLevel`/`usdKrwLevelAsOfDate`, `vixLevel`/`vixLevelAsOfDate`)를
그대로 따라 각 신규 값도 `<이름>`/`<이름>AsOfDate` 쌍으로 추가:

```
usFedFundsRate, usFedFundsRateAsOfDate
usTreasury10y, usTreasury10yAsOfDate
usNasdaq, usNasdaqAsOfDate
krKospi, krKospiAsOfDate
krTreasury3y, krTreasury3yAsOfDate
krCorpAA3y, krCorpAA3yAsOfDate
krCreditSpreadBp, krCreditSpreadBpAsOfDate
krCpi, krCpiAsOfDate
krLeadingCyclical, krLeadingCyclicalAsOfDate
krCoincidentCyclical, krCoincidentCyclicalAsOfDate
```

`AsOfDate` 컬럼의 의미가 일별과 월별에서 다르다는 점을 명시적으로 남긴다 —
일별은 "그 값이 관측된 실제 날짜", 월별은 "그 값이 usableFromDate 계산을 거친
날짜"다(원 참조월 자체는 아니다). 이 구분을 잊으면 나중에 "왜 vixLevelAsOfDate는
관측일인데 krCpiAsOfDate는 아니냐"는 혼동이 생긴다 — 그래서 여기 적어 둔다.

---

## 8. 기존 market-regime과 통합할 schema — 별도 시스템을 안 만든다

`lib/marketRegimeEngine.js`의 4축 정의(VIX·trend60·breadth·USD/KRW 20일변화율,
`-4~+4` 합산)는 **이번 설계로 바꾸지 않는다** — CLAUDE.md 원칙("고정, 이후 전략
성과로 역최적화 안 함")이 그대로 유지된다. 이번에 추가하는 10개는 **그 4축과
나란히 놓이는 새 컬럼일 뿐**, 기존 regime 점수식에 자동으로 안 들어간다 — 새
축(금리·신용·경기·물가)을 실제 regime 점수에 반영할지는 **별도 결정**이다
(사용자 지시 §10 "실제 백필은 여기서 중단"과 같은 경계 — 이 설계 문서는 그
결정 이전 단계).

---

## 9. synthetic data PIT selftest — 결과

`test_macro_regime_layer_pit.py`(신규, 이 세션에서 작성) — 네트워크 없이 두
층위를 검증한다:

1. **일별 시리즈**: 기존 `macro_common.py::selftest_asof_join()`을 그대로
   재사용(무변경) — 이미 통과 확인된 4개 성질(등호배제·연속거래일·주말갭·
   이력이전 NaN)을 신규 시리즈에도 같은 함수가 적용됨을 보인다.
2. **월별 시리즈 lag 합성**: CPI(참조월 말일+5일)·경기종합지수(참조월 말일+60일)
   각각 합성 관측치를 만들고, `usableFromDate` 계산 후 `asof_join_kr()`에 넣어
   "발표 전날엔 이전 달 값(또는 NaN), 발표일 당일부터 새 값"을 직접 확인한다.
3. **파생값(신용스프레드) 결측 전파**: 한쪽 입력이 NaN인 날짜에서 결과도 NaN인지
   확인한다.

실행 결과(2026-08-23, 실제 실행 — 첫 실행에서 1건 FAIL 발견·수정 경위는 아래 참고):

```
$ python test_macro_regime_layer_pit.py
[PASS] [일별-재사용] D당일 FRED 관측치를 쓰지 않는다(등호 배제)
[PASS] [일별-재사용] 연속 거래일에서는 하루 전 값을 쓴다
[PASS] [일별-재사용] 주말 갭도 backward-fill로 자연 처리된다
[PASS] [일별-재사용] FRED 이력 이전 날짜는 NaN(기본값 금지)
[PASS] [월별-CPI] 발표일(02-05) 당일엔 등호배제로 아직 이전 달(Dec=99.0)
[PASS] [월별-CPI] 발표 다음 거래일(02-06)부터 신규값(Jan=100.0) 반영
[PASS] [월별-CPI] 다음 발표(03-05) 당일도 등호배제로 이전 값(Jan=100.0) 유지
[PASS] [월별-CPI] 다음 거래일(03-06)부터 Feb=101.0 반영
[PASS] [월별-경기지수] 12월분 usableFromDate가 +60일 균일규칙으로 자동으로 늦게 잡힘
[PASS] [월별-경기지수] 첫 관측 이전(2026-01-01)엔 NaN(지어내지 않음)
[PASS] [파생-신용스프레드] 두 입력 다 있으면 정상 계산(01-07: 4.6-3.8=0.8 -> 80bp)
[PASS] [파생-신용스프레드] 국고채 이력 이전(01-04, 회사채는 값 있음)엔 NaN 전파(지어내지 않음)

전체 12건 중 12 PASS, 0 FAIL
```

**첫 실행에서 실제로 1건 FAIL이 났었다** — `krCreditSpreadBp` 결측 전파 테스트를
처음엔 "국고채 값이 하루(01-06) 빠진" 시나리오로 짰는데, 그 하루는 `asof_join_kr`의
backward-fill이 01-05 값을 정상적으로 끌어와 **결측이 아니라 정상값**이 나왔다
(테스트 설계 오류였지 `asof_join_kr`의 결함이 아니었다). "진짜 결측"(그 시리즈의
이력 자체가 시작되기 전)과 "다음 시리즈로 forward-fill되는 정상 구간"을 헷갈리면
안 된다는 걸 이 스크립트를 만들면서 직접 겪었다 — 회사채는 01-03부터, 국고채는
01-05부터 이력이 있게 고쳐 01-04(국고채 이력 이전)에서 진짜 NaN 전파를 확인하도록
수정한 뒤 전체 통과.

(스크립트 자체는 `test_macro_regime_layer_pit.py` 참고 — 재실행하면 동일 결과.
synthetic 데이터만 쓰므로 네트워크 불요.)

---

## 10. 이 설계가 하지 않은 것

- **실제 백필 실행 없음** — ECOS·FRED·네이버에서 실제 전체 이력을 받아
  `macro_regime_features.parquet`에 쓰는 작업은 이 문서 범위 밖(사용자 지시
  §10). 백필 스크립트 자체도 아직 안 짬.
- CPI·경기종합지수 lag 상수(5일·60일)는 **웹검색 기반 추정**이다 — 백필 실행
  전 통계청 공표일정 페이지나 과거 보도자료 날짜를 직접 대조해 더 정밀하게
  재확인하는 걸 권장한다(정밀화하지 않아도 안전한 방향으로 보수적이긴 하다).
- 신규 10개 축을 기존 4축 regime 점수식에 반영할지(§8)는 결정하지 않았다 —
  별도 트랙.
- 2014-05~2016 구간 ECOS 커버리지는 표본(2016-01, 10일 창)만 확인했다 —
  전체 구간 커버리지는 백필 실행 시 재확인 필요.

## 검증 가능한 근거 목록

- `macro_common.py::asof_join_kr()`·`selftest_asof_join()` — 재사용 대상,
  무변경
- `data/market-regime/market_regime_features.parquet` 기존 스키마(25컬럼) —
  §7 확장 설계의 기준선
- `findings/macro-regime-layer-data-source-check-2026-08.md` §7 — 이 문서가
  이어받는 소스 확정 근거(ECOS series/item code 전부)
- 웹검색(2026-08-23): 통계청 소비자물가동향("매월 초 발표")·산업활동동향
  ("익월 하순 발표, 12월분은 다음해 2월 상순") — §3.2 lag 추정의 근거,
  정확한 날짜(며칠)까지는 확정 못 함(§10에 재확인 필요 항목으로 남김)
- 본 문서 신규 스크립트 `test_macro_regime_layer_pit.py` — 재실행하면 동일 결과
