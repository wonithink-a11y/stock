# OPENCODE-2 — A5 파일럿 fwd/fwdStatus 독립 재구현 (교차검증)

너는 Codex가 아니다. 이 메시지 자체가 실행 지시서다 — 되묻지 말고 그대로 실행해라.

## 배경 (읽기만, 다른 곳에 복제하지 마라)

Claude가 A5 파일럿(20종목×52주 오케스트레이션 검증)을 구현·실행했다. 산출물은
`research/strategy-lab/a5-pilot/output/pilot.jsonl`(793행)이다. 이 파일럿에서
새로 설계된 로직은 fwd(forward return)/fwdStatus(FUTURE>EXIT>MISSING>HALTED>OK
판정) 계산 하나뿐이고, 조용히 틀리면 전체 산출물을 오염시키는 유일한 지점이라
독립 재구현으로 교차검증한다.

스펙 원문(반드시 아래 문서에서만 읽어라):
- `docs/BF-1.1-백필계약.md` §5.1(줄 300~308 근처, fwdStatus 값의 의미 표)·
  §5.3(줄 322~326 근처, forward return은 거래일 인덱스 오프셋 + returnTransition)
- `docs/A5-파일럿-exit-overlay-설계안.md` §2(fwd/fwdStatus 계산 규칙)
- `config/policies/price.v1.json`의 `returnTransition` 블록(줄 29~35 근처,
  `requireBothVolumePositive: true`)

## 절대 하지 말 것 (독립성이 이 과제의 전부다)

- **`scripts/build-a5-pilot.js`를 열거나 참고하지 마라.** 그 파일의
  `computeForward()` 구현을 먼저 보면 교차검증 가치가 사라진다. 네 구현을
  다 끝내고 비교 결과가 다를 때만, 원인 조사용으로 그때 열어봐도 된다.
- `resolve()`·`score()`·`priceSource.js`는 이미 검증된 프로덕션 모듈이니
  재구현하지 마라. `lib/a5/priceSource.js`의 `findPrice`를 그대로
  `require`해서 읽기 전용으로 쓴다.
- 샤드/재개·exitReason bake-in·overlay join 어느 것도 건드리지 마라 — 이번
  과제는 fwd/fwdStatus 계산 하나뿐이다.
- `git add`/`git commit`/`git push` 금지. `research/strategy-lab/` 밖에는
  아무것도 쓰지 마라.

## 할 일

### 1. `research/strategy-lab/a5-pilot-independent/build-fwdstatus-independent.js` 신설

스펙 문서만 보고 아래 규칙을 독립적으로 구현한다(내부 구현·함수 시그니처는
자유, 판정 규칙만 지켜라):

각 horizon h ∈ {20, 60, 120}에 대해(출력 키는 `d20`/`d60`/`d120`):

1. `targetIdx = tradingDays에서 asOf의 인덱스 + h`
2. `targetIdx`가 `tradingDays` 길이 이상이면 → `fwdStatus: "FUTURE"`, `fwd: null`
3. 아니면 `targetDate = tradingDays[targetIdx]`. 그 종목의 `exitAtConfirmed`가
   있고 `targetDate > exitAtConfirmed`면 → `fwdStatus: "EXIT"`, `fwd: null`
4. 아니면 `targetDate`의 가격을 `findPrice(ticker, targetDate)`로 조회한다.
   없으면 → `fwdStatus: "MISSING"`, `fwd: null`
5. `asOf`의 가격(`snapshotPrice`)과 `targetDate`의 가격(`targetPrice`) 중
   하나라도 `volume <= 0`이면 → `fwdStatus: "HALTED"`, `fwd: null`
   (`returnTransition.requireBothVolumePositive`)
6. 그 외 → `fwdStatus: "OK"`, `fwd: (targetPrice.close - snapshotPrice.close) / snapshotPrice.close`

**우선순위는 반드시 1→6 순서로, 먼저 맞는 조건 하나만 적용한다**
(FUTURE > EXIT > MISSING > HALTED > OK).

### 2. 20종목 × 52스냅샷 격자 전체에 대해 계산

스냅샷 구간: `data/backfill/calendar.json`의 `snapshotDays` 중
`2025-06-20` ~ `2026-06-12`(52개) — 파일에서 직접 필터링해라, 하드코딩하지 마라.

20종목(ticker, corp) — 그대로 써라:

```
005930 00126380   000660 00164779   005380 00164742   035420 00266961
051910 00356361   000270 00106641   105560 00688996   017670 00159023
230980 01110076   140910 00860730   044060 00291860   495900 01872893
451700 01712616   257990 00425254   439410 01675254   449020 01701753
208340 00972293   008110 00157104   096040 00480756   003560 00154426
```

`exitAtConfirmed`는 corp별로 `data/backfill/price/a2b/delisted-exit.jsonl.gz`
(gzip, zlib으로 풀어라)에서 `corp`로 찾아 `exitAtConfirmed` 필드를 쓴다. 앞의
8종목(005930~017670)은 이 파일에 없다 — 이 경우 `exitAtConfirmed: null`로
취급해라(활성 종목).

각 (ticker, asOf) 쌍마다 `asOf`의 가격이 없으면 그 셀은 건너뛴다(레코드를
만들지 않는다) — Claude 산출물과 같은 스킵 규칙이다.

### 3. `research/strategy-lab/a5-pilot-independent/comparison.json` 작성

Claude의 `research/strategy-lab/a5-pilot/output/pilot.jsonl`(각 행에 `t`·`d`·
`fwd`·`fwdStatus` 필드 있음)과 네 결과를 `(ticker, asOf)` 키로 조인해서:

- 양쪽 다 레코드가 있는 셀 수(비교 가능 총 수)
- d20/d60/d120 각각 `fwdStatus` 일치 건수 · 불일치 건수
- `fwdStatus`는 같은데 `fwd` 수치가 다른 건수(0.0001 이내 오차는 일치로 본다)
- 불일치 샘플 최대 20건: `{ticker, asOf, horizon, claude: {fwdStatus, fwd}, yours: {fwdStatus, fwd}}`

### 4. `research/strategy-lab/a5-pilot-independent/findings.md` 작성

한국어로 결과를 요약한다 — 일치율, 불일치가 있다면 어느 쪽이 스펙에 더
맞아 보이는지 네 판단을 적어라. 단 이건 최종 판단이 아니라 "이 지점을
다시 보라"는 신호라고 명시해라(AGENTS.md §4 — 불일치는 누가 틀렸다는
뜻이 아니라 더 볼 지점이 있다는 신호).

## 완료 후

전체 stdout(각 단계 로그)과 `comparison.json`의 요약 수치를 대화로 그대로
보고한다. 판단하지 말고 숫자만 보고한다 — 최종 판단은 Claude와 사용자가 한다.
