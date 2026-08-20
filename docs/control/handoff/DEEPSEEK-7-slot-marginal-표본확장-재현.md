# DEEPSEEK-7 — slot-marginal 표본 확장 재현 (Codex 발견 §5 한계 후속)

```
발행   2026-08-20 · Claude
대상   DeepSeek (읽기 전용 — 저장소에 아무것도 쓰지 않는다. git add/commit/rm 전부 금지.
       production 코드(lib/·scripts/·config/)는 읽기만, 수정 금지)
배경   research/strategy-lab/findings/slot-marginal-contribution/SLOT-MARGINAL-
       CONTRIBUTION.md(Codex, 2026-08-19)가 KR-2.2 19개 슬롯의 marginal
       contribution을 120종목 표본(seed=20260819)으로 측정했다. 그 문서 §5
       한계 1번: "표본은 120종목 샘플이다. 전체 유니버스가 아니다. 표본 추출
       bias 가능성은 남아 있다." 이걸 확인한다 — 표본을 키워도 핵심 결론이
       유지되는지
```

## 원 결론(재확인 대상, 120종목 기준)

```
1  base(재무+기술)가 최소 비교 4종 중 유일하게 유의한 IC(d120 rankIC +0.0422, t=3.48)
2  full 모델에서 IC를 결정적으로 올리는 슬롯은 pbr 하나 (ΔIC d120 = +0.0385)
3  수급 슬롯의 5일 추세 정의는 음(-) marginal — A4 20일 누적과 반대 방향
4  base는 coverage 60%를 원리적으로 못 넘는다(최대 0.579)
```

## 할 일

`research/strategy-lab/slot_marginal_analysis.js`(38행 `SEED = 20260819`,
37행 `SAMPLE_SIZE = 120`)와 `research/strategy-lab/analyze_slot_marginal.py`를
**저장소 안에서 직접 고치지 말고** 임시 디렉터리로 복사해서, 거기서 아래 두 세트로
다시 실행해라:

```
세트 A   SAMPLE_SIZE = 400, SEED = 20260820 (원본과 다른 시드)
세트 B   SAMPLE_SIZE = 400, SEED = 20260821 (또 다른 시드 — 시드 자체의 영향도 보려면)
         시간이 부족하면 세트 A 하나만 해도 된다
```

각 세트에서:
```
1  §3.1의 최소 비교 4종(base/base_foreign/base_inst/base_both) pooled Spearman
   IC(d20/d60/d120) — 120종목 결과와 나란히 비교
2  §3.2의 LOO marginal — 적어도 pbr·institutionNetBuy5d·foreignNetBuy5d·
   debtRatio(음수였던 것 하나)는 반드시 다시 재고, ΔIC 방향(+/-)이 뒤집히는
   슬롯이 있는지 확인
3  §3.4의 coverage sufficiency rate(base 기준 0.0%가 표본 키워도 유지되는지)
```

## 확인할 것 — 표본이 늘면 뭐가 달라지는가

```
a  결론 1~4(위)이 400종목에서도 방향·유의성이 유지되는가
   (수치는 달라져도 된다 — "부호와 유의성이 같은가"가 핵심)
b  120종목 결과와 400종목 결과의 차이가 표본 크기 효과로 설명되는 범위인가,
   아니면 120종목 표본이 진짜로 편향돼 있었다는 신호인가
c  실행 시간·리소스가 부담되면(예: 400종목이 너무 오래 걸리면) 200종목으로
   낮춰도 된다 — 단 그 경우 왜 낮췄는지 적어라
```

## 하지 말 것

```
✗ 저장소 파일(slot_marginal_analysis.js·analyze_slot_marginal.py 원본)을 고치지
  마세요 — 복사본에서만 작업. research/strategy-lab/findings/에도 쓰지 마세요
✗ git add/commit/rm 금지
✗ "표본을 늘려도 똑같다"를 확정으로 말하지 마세요 — 숫자로 보여줘라
```

## 산출 형식

```
1  세트별 표 — §3.1 최소비교 4종 IC, §3.2 LOO marginal(주요 슬롯만)
2  120종목 vs 400종목 비교 표
3  결론 — 원 발견(pbr 지배적·5일 수급 역방향·coverage 트레이드오프)이 표본
   확장 후에도 버티는가
4  특히 확인된 것(최대 3개)
5  확인 / 추정 / 미확인
```

## 결과 전달

대화로 Claude에게 전달하면, Claude가 결과를 검토해 CLAUDE.md·docs/verification에
반영할지, KR-2.3 재검토 시점에 참고 자료로 쓸지 결정한다.
