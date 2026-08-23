# market-regime 정의 — VIX·trend·breadth·USD/KRW 4축 (2026-08)

설계 원칙: **regime 정의을 어떤 전략의 수익률에도 맞춰 최적화하지 않는다.** 임계값은 (a) 기존 production 관례(VIX)이거나 (b) 그 feature 자신의 전체 히스토리 tercile(trend·breadth·USD/KRW)뿐이다 — 전략 성과는 이 정의를 고정한 뒤 별도 단계에서 측정한다(이번 문서 범위 밖).

선행 문서: `findings/market-regime-feature-semantics-2026-08.md`(rvol20↔impl_corr20 중복 확인 → 이번 정의에서 realized_vol 축 제외, VIX만 사용).

---

## 1. 4축 정의

| 축 | 컬럼 | 임계값 산출 방식 | Low/Bear/Weak/Falling | Mid/Neutral | High/Bull/Strong/Rising |
|---|---|---|---|---|---|
| VIX | `vixLevel` | **production 관례 재사용**(`scripts/fetch_macro.py:179`, 원본 무변경) | <20 | 20~30 | >=30 |
| 추세 | `trend60` | 자기 히스토리 tercile(33/67분위) | <-0.0169 | -0.0169~0.0596 | >=0.0596 |
| breadth | `adv_pct` | 자기 히스토리 tercile | <0.2793 | 0.2793~0.4135 | >=0.4135 |
| USD/KRW | `usdKrw20dChangePct` | 자기 히스토리 tercile | <-0.6397 | -0.6397~1.1388 | >=1.1388 |

**VIX만 tercile이 아니라 production 임계값을 쓴 이유**: 이미 이 프로젝트가 운영 대시보드에서 쓰고 있는 값이라(2026-08-10 이전부터), 이번 연구를 위해 새로 고른 값이 아니다 — 데이터 스누핑 우려가 가장 낮은 선택지다. 나머지 3축은 이 프로젝트에 그런 기존 관례가 없어 tercile로 대신했다.

## 2. 축별 상태 분포 (실측, 균형 확인용)

tercile로 나눈 3축은 정의상 각 상태가 정확히 ~33%씩 나와야 한다 — VIX만 production 임계값이라 분포가 균등하지 않을 수 있다(실제로 그런지 아래에서 직접 확인).

- **VIX**: Low 69.3%, Mid 24.9%, High 5.7%
- **trend60**: Neutral 33.3%, Bear 33.3%, Bull 33.3%
- **breadth(adv_pct)**: Strong 33.5%, Weak 33.3%, Neutral 33.3%
- **USD/KRW 20d**: Rising 33.3%, Neutral 33.3%, Falling 33.3%

## 3. 조합 규칙 — Risk-On / Neutral / Risk-Off

각 축 상태를 -1/0/+1로 점수화(방향은 표준적 위험선호·회피 해석으로 **사전 고정** — 데이터로 부호를 정하지 않음): VIX 낮음=+1, 추세 상승=+1, breadth 강함=+1, USD/KRW 하락(원화강세)=+1. 4축 합(-4~+4)을 3구간으로 묶는다: **합계>=+2 → Risk-On, 합계<=-2 → Risk-Off, 그 외 → Neutral.**

최종 분포(실측): Neutral 56.7%, Risk-On 31.8%, Risk-Off 11.4%

결측(4축 중 하나라도 NaN이라 regime 미산정) 행수: 9 / 2604

## 4. PIT

regime label에 쓰인 4개 원천 컬럼(`vixLevel`·`trend60`·`adv_pct`·`usdKrw20dChangePct`)은 이미 `market_regime_features.parquet`에서 PIT 검증(quality audit 19/19 PASS)을 마친 값이다. regime label도 그 값들과 같은 `usableFromDate`(=date+1 거래일)를 그대로 물려받는다 — 새 PIT 규칙을 만들지 않았다. 4축 중 하나라도 결측인 날은 regime을 지어내지 않고 `None`으로 둔다(절대 규칙 1과 같은 원칙).

## 5. 다음 단계 (이번 문서 범위 밖)

이 정의를 **고정한 채** Opening Fade·CAND1·H6 전략의 regime별 성과를 측정하는 것이 다음 단계다(사용자 로드맵 §5). 이번 정의 자체는 어떤 전략의 수익률도 보지 않고 만들어졌다는 점이 그 비교의 전제조건이다.

## 검증 가능한 근거 목록

- `data/market-regime/market_regime_features.parquet` — 4축 원천
- `data/market-regime/regime_labels.parquet` — 이 문서의 실측 산출물(감사용)
- `scripts/fetch_macro.py:179` — VIX 임계값 원출처(원본 무변경)
- `findings/market-regime-feature-semantics-2026-08.md` — realized_vol 축 제외 근거(rvol20↔impl_corr20 r=0.948)
- 본 스크립트 `build_regime_definition.py` — 재실행하면 동일 결과
