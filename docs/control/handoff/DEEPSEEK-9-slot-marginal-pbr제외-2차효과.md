# DEEPSEEK-9 — pbr 제외 후 2차 효과 (DEEPSEEK-7 후속)

```
발행   2026-08-20 · Claude
대상   DeepSeek (읽기 전용 — 저장소에 아무것도 쓰지 않는다. git add/commit/rm 전부 금지.
       production 코드(lib/·scripts/·config/)는 읽기만, 수정 금지)
배경   docs/verification/DEEPSEEK-7-slot-marginal-표본확장-결과.md가 확인:
       pbr 하나가 full 모델 IC를 지배한다(제거 시 IC 반토막). 나머지 슬롯의
       marginal은 전부 작다(|ΔIC|<0.01). 이게 "다른 슬롯이 진짜 무효과"인지,
       "pbr이 신호를 가려서(masking) 안 보이는" 것인지 구분이 안 됐다
```

## 할 일

`research/strategy-lab/slot_marginal_analysis.js`·`analyze_slot_marginal.py`를
저장소 밖 복사본(예: DEEPSEEK-7이 쓴 `%TEMP%\opencode\slot-marginal-400\` 같은
패턴)에서 고쳐서, **"full에서 pbr 하나만 뺀 것"을 새 베이스라인으로 두고
LOO를 다시 돌려라**:

```
새 베이스   full_minus_pbr = full(17개 슬롯) - pbr (16개 슬롯)
LOO(재정의) full_minus_pbr에서 나머지 16개 슬롯을 하나씩 더 빼고
            ΔIC = IC(full_minus_pbr) - IC(full_minus_pbr - slot)
```

표본은 DEEPSEEK-7의 세트 A(400종목, SEED=20260820)를 그대로 써라(이미 있으면
재사용, 없으면 같은 방식으로 새로 생성).

## 확인할 것

```
a  IC(full) vs IC(full_minus_pbr) — 얼마나 떨어지는지(DEEPSEEK-7이 이미
   0.0466→0.0224 확인함, 재확인만)
b  full_minus_pbr 기준 LOO에서 어떤 슬롯의 ΔIC가 원래(pbr 포함 full 기준)보다
   커지는가 — pbr이 없으면 "가려졌던" 신호가 드러나는 슬롯이 있는지
c  institutionNetBuy5d·foreignNetBuy5d(수급 슬롯)이 pbr 제외 후에도 여전히
   작은 marginal인지, 아니면 커지는지 — KR-2.3(수급 재정의) 판단에 직결됨
d  가장 커진 슬롯이 있다면 그게 pbr과 상관관계가 높은 슬롯인지 확인해라
   (raw correlation 한 줄이면 된다) — masking의 메커니즘 설명
```

## 하지 말 것

```
✗ 저장소에 파일 쓰지 마세요 — 전부 저장소 밖(%TEMP% 등)에서
✗ production 코드 수정 금지
✗ "pbr을 production에서 빼자/넣자"를 제안하지 마세요 — 이건 순수 진단이다.
  정책 제안은 Claude 몫이다
```

## 산출 형식

```
1  IC(full) vs IC(full_minus_pbr) 비교
2  full_minus_pbr 기준 LOO 표(16개 슬롯, ΔIC d20/d60/d120) — 원 full 기준 LOO와
   나란히
3  가장 크게 달라진 슬롯 top 3와 그 슬롯-pbr raw correlation
4  결론 — masking 효과가 실제로 있는가, 있다면 어느 슬롯에서
5  확인 / 추정 / 미확인
```

## 결과 전달

대화로 Claude에게 전달하면, Claude가 docs/verification/에 옮겨 적는다.
