---
track: kr
factor: pbr-reproducibility-anchor
date: 2026-09-08
verdict: UNCLASSIFIED
criteria_version: backfill-v1
conditions: ["새 백테스트 아님 - 재현성 사슬 점검과 출처 고정만 한다", "기존 판정(pbr-combined-oos-validation KEEP)을 바꾸지 않는다", "파라미터를 재선택하지 않는다", "인용값이 다른 기존 findings 를 소급 수정하지 않는다"]
reason: >-
  CLAUDE.md 가 미해결로 적어 둔 "pbr_value_v1/ 재현성 사슬"을 점검했다. 끊긴
  자리는 '소스가 없다'가 아니라 '출처 기록이 없다'였다 - valuation-panel.jsonl
  은 전부 커밋된 입력에서 `node scripts/build-a5-valuation-panel.js` 한 줄로
  재생성되고, 전략 디렉터리 4종도 이미 커밋돼 있다(2026-08-26 인수인계의
  "미커밋" 서술은 낡았다). 재현이 안 됐던 이유는 어떤 패널 빌드가 어떤 숫자를
  냈는지가 어디에도 안 남아서다. 생성기가 sha256·행수·기간을 담은 manifest 를
  쓰도록 고치고, 현재 빌드(sha256 e55330bf2115, 175,250행, asOf 2016-01-04~
  2026-09-01)를 사후 기록해 앵커로 고정했다. 이 패널이 baseline CAGR 5.49%
  (Sharpe 0.521 · MDD -21.09% · 청산 777)를 낸 것이고, 독립 실행 2건이
  소수점까지 일치하므로 5.49% 가 정본이다(기존 인용값 4.72% 는 이전 패널 기준).
  점검 중에 별건이 하나 나왔다 - pbr_value_v1_combined 의 committed policy 는
  nDrop=3 인데 KEEP 판정을 받은 finding 이 선택한 값은 nDrop=2 다. 라이브
  페이퍼 슬리브가 검증된 파라미터가 아닌 값으로 돌고 있다. 파라미터를 임의로
  바꾸지 않고 보고만 한다(사용자 결정).
cagr: 5.49
sharpe: 0.521
mdd: -21.09
win_rate: null
n: 777
t_stat: null
stats:
  panelAnchor:
    sha256: "e55330bf21155a774c6ef0dc9a56243fcb88e3a359c6a5de6e7e6a2ff773b804"
    rows: 175250
    pbrRows: 126434
    pbrCoveragePct: 72.14
    asOfRangeObserved: ["2016-01-04", "2026-09-01"]
    generatedAt: "2026-09-03T23:58:03"
  baselineTop30Full: {cagr: 5.49, sharpe: 0.521, mdd: -21.09, closed: 777}
  priorCitedBaseline: {cagr: 4.72, note: "이전 패널 빌드 기준. 소급 수정하지 않는다"}
  combinedParamMismatch:
    committedPolicy: {nDrop: 3, maxExclusionPercentile: 0.8, topN: 30, maxPositions: 30}
    findingSelected: {nDrop: 2, maxExclusionPercentile: 0.8}
    trainSharpeOriginal: {nDrop2: 0.6943, nDrop3: 0.6780}
    trainSharpeReproduced: {nDrop2: 0.6519, nDrop3: 0.7171}
---

# PBR 재현성 — 사슬 점검과 출처 앵커 고정 (2026-09-08)

CLAUDE.md 의 "`pbr_value_v1/` 재현성 사슬 완성은 여전히 미해결" 항목과
`market-benchmark-comparison-2026-09.md` §6-2(인용값 4.72% 가 재현되지 않음),
`keep-paper-candidate-final-verification-2026-09.md` §4-2(nDrop 최선 뒤집힘)를
한 자리에서 처리한다. **새 백테스트가 아니다.**

## 1. 사슬은 소스에서 끊겨 있지 않았다

`scripts/build-a5-valuation-panel.js` 의 입력을 전부 확인했다.

```
data/backfill/calendar.json              커밋됨
data/backfill/universe/a1a/current.jsonl 커밋됨
data/backfill/fundamentals/a3d/*.jsonl.gz 커밋됨
data/backfill/price/a2a/                 15개 추적
data/backfill/fundamentals/a3            13개 추적
data/backfill/fundamentals/a3c           12개 추적
lib/a5/resolver.js                       커밋됨
```

전부 커밋돼 있다. 즉 패널은 **한 줄로 재생성된다**:

```bash
node scripts/build-a5-valuation-panel.js --end 2026-09-02
```

전략 디렉터리도 마찬가지다 — `pbr_value_v1`·`_combined`·`_dropout`·`_maxexcl`
넷 다 4개 파일씩 추적 중이다. **`세션인수인계-2026-08-26.md` §3 의 "재현성
사슬이 없어서 로컬 전용으로 남긴다" 서술은 그 뒤에 커밋되면서 낡았다.**
CLAUDE.md 의 "미해결" 도 같은 이유로 절반만 맞다.

## 2. 끊겨 있던 것은 출처 기록이다

재현이 안 됐던 진짜 이유는 **어떤 패널 빌드가 어떤 숫자를 냈는지가 아무 데도
안 남아서**다. 패널은 `reports/` 안(gitignore)에 있고 파일명에 버전이 없다.
`--end` 를 바꿔 다시 만들면 조용히 다른 파일이 되고, 그걸로 낸 CAGR 이 달라져도
왜 달라졌는지 짚을 근거가 없다. 4.72% → 5.49% 가 정확히 그 모양이었다.

고친 것 둘.

1. **생성기가 manifest 를 쓴다.** `valuation-panel.manifest.json` 에
   `generatedAt · start · end · rows · pbrRows · pbrCoveragePct · sha256 ·
   gitHead` 를 남긴다. findings 는 앞으로 이 `sha256` 과 `end` 를 인용한다.
2. **현재 빌드를 사후 기록해 앵커로 고정했다.**

```
sha256   e55330bf21155a774c6ef0dc9a56243fcb88e3a359c6a5de6e7e6a2ff773b804
rows     175,250 (pbr 126,434 = 72.14%)
asOf     2016-01-04 ~ 2026-09-01   (실측)
mtime    2026-09-03T23:58:03
```

★ **패널을 재생성하지 않았다.** 다시 만들면 상류가 그새 갱신된 만큼 값이
움직여 지금 고정하려는 앵커 자체가 사라진다. 사후 manifest 의 `gitHead` 와
CLI `end` 는 확인할 수단이 없어 `null` 로 뒀다 — 추정해 채우지 않는다(교훈57).
대신 잴 수 있는 `asOfRangeObserved` 를 남겼다.

## 3. baseline 정본은 5.49% 다

```
baseline_top30_full   CAGR 5.49% · Sharpe 0.521 · MDD -21.09% · 청산 777
```

독립 실행 2건이 소수점까지 일치한다 — `market-benchmark-comparison-2026-09`
(Claude)과 `pbr-topn-strength-oos-2026-09`(실험실, `baseline_top30_full`:
cagr 0.0549 · sharpe 0.5189 · mdd -0.2109 · closed 777). 위 앵커 패널이 낸
값이다.

**기존 findings 10여 건이 인용하는 4.72% 는 소급 수정하지 않는다.** 그것은
이전 패널 빌드에서 실제로 나온 값이고, 날짜가 박힌 관측치를 다른 날 값으로
고쳐 쓰면 기록이 아니라 소설이 된다. 앞으로 baseline 을 인용할 때 5.49% 와
위 sha256 을 함께 쓴다.

## 4. ★ 점검 중 나온 별건 — 라이브가 검증된 파라미터로 돌고 있지 않다

`pbr_value_v1_combined` 는 페이퍼 트레이딩 4개 슬리브 중 하나다.

```
committed policy.json   nDrop = 3   maxExclusionPercentile = 0.8
KEEP finding 이 선택한 값 nDrop = 2   maxExclusionPercentile = 0.8
```

`pbr-combined-oos-validation-2026-08.md`(verdict KEEP)의 conditions 는
`"nDrop=2/maxexcl=0.8 선택"`, reason 은 `"TRAIN 최선(nDrop=2/maxexcl=0.8)이
전체기간 선택과 정확히 일치 - production 고려 후보로 상향"` 이다. 그런데 그
문서 자신의 격자표에서 nDrop=3/0.8 은 **"첫 결합실험 값"**, 즉 선택 이전의
기본값으로 적혀 있다.

policy.json 은 커밋이 하나뿐이고(`f0c282d`, 2026-08-31 일괄 백업 커밋) 처음부터
nDrop=3 이었다. **의도적으로 3 으로 맞춘 흔적이 없다** — 선택 결과가 파일에
반영되지 않은 채로 라이브에 올라간 것으로 보인다.

### 그런데 지금 2 로 바꾸면 안 된다

실험실 재현(`keep-paper-candidate-final-verification-2026-09` §2.1)에서 TRAIN
최선이 뒤집혔다.

```
              원본 TRAIN Sharpe    재현 TRAIN Sharpe
nDrop=2/0.8       0.6943               0.6519
nDrop=3/0.8       0.6780               0.7171   ← 현재 데이터의 TRAIN 최선
```

"TRAIN 최선을 고른다"는 규칙을 지금 데이터에 적용하면 **3 이 나온다.** 즉
현재 파일이 우연히 지금 규칙과 일치한다. 데이터가 조금 갱신될 때마다 1위가
2↔3 으로 오가는 것은 **둘이 구분되지 않는다**는 뜻이고, 이 저장소가 반복해서
데인 패턴이다(`pbr-topn-strength-oos` TRAIN→VALID 순위 완전 역전,
`pbr-roe-quality-overlay-oos` gate50, `factor-earnings-yield-selection-refresh-
recheck-2026-09` 의 mp=30↔50). **어느 쪽으로든 지금 바꾸는 것은 노이즈를
쫓는 행위다.**

OOS 부호 반전 0건은 두 경우 모두 유지되므로 KEEP 판정은 흔들리지 않는다.

### 남기는 것

- 파라미터를 바꾸지 않았다. **문서와 실물이 어긋나 있다는 사실**을 고정한다.
- 어느 값으로 확정할지는 사용자 결정이다. 확정되면 그때
  `tests/test_paper_sleeve_policy.py` 에 pin 을 추가한다 — 지금 추가하면
  미해결 불일치를 테스트가 축복하게 된다.
- maxPositions tripwire 는 이미 있다(커밋 `41a5732`). 이번 건은 그 tripwire 가
  보는 필드(`portfolio`) 밖이라 안 걸렸다.

## 5. 남은 것

- **`--end` 를 바꾼 재생성**: 앞으로는 manifest 가 자동으로 남는다. 옛 빌드들의
  출처는 복원 불가다(파일이 이미 없거나 덮였다) — 소급하지 않는다.
- **`run_pbr_value_v1.py` 의 실현손익 회계**: CLAUDE.md 함정 (5)가 미수정으로
  적어 둔 항목이고 이번에 손대지 않았다. baseline 5.49% 는 MTM 회계로 낸
  값이라(`pbr-topn-strength-oos` 조건에 `MTM 회계` 명시) 이 앵커 자체는
  영향받지 않는다.
