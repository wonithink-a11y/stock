# DEEPSEEK-4 — 저장소 루트 미커밋 스크립트 24개 정리 감사 (분류만, 커밋은 Claude가 함)

```
발행   2026-08-20 · Claude
대상   DeepSeek (읽기 전용 — 분류·요약만 한다. 저장소에 아무것도 쓰지 않는다,
       커밋·삭제·수정 전부 금지)
배경   DEEPSEEK-3(docs/control/handoff/DEEPSEEK-3-미커밋파일-정리-감사.md)가 같은
       파일들(그 문서의 "D. 저장소 루트 스크래치 파일" 항목)을 다뤘지만 표 출력이
       도중에 끊겨 결과가 하나도 저장되지 않았다. 그 문서를 참고하되, 이 문서가
       그 항목의 재실행이다 — 이미 처리된 A/B/C 항목은 보지 마라.
```

## 이미 결정된 것 (다시 볼 필요 없음)

```
HANDOVER_2026-08-17.md   ★ 보류 확정 — 다른 문서가 "구식, same-bar 231건은 틀렸고
                           130건이 맞다"고 명시. 이 파일은 대상에서 제외한다
scratch-a4-runbacktest-comparison.json · scratch-a4-supplydemand-vertical-slice.json
                         이미 커밋됨 — 저장소에 없다. 대상 아님
```

## 분류 대상 (저장소 루트, 24개)

```
analyze_candidates.py · audit_samebar_stop.py · audit_search.py ·
check_corp_action.py · check_data.py · check_excluded.py · check_foreign.py ·
check_foreign2.py · check_pkl.py · classify_impact.py · convert_a2a.py ·
corp_action_analysis.json (20KB) · final_classification.py · read_files.py ·
same_bar_stops.json (36KB) · temp_a4_keys.txt · temp_scratch.txt ·
temp_scratch2.txt · test_load.py · verify_5dc.py · verify_a1b_pnl.py ·
verify_commit.py · verify_survivorship.py · verify_trend.py
```

## 각 항목마다 확인할 것

```
1  한 줄 요약 — 이게 뭘 하는/담고 있는 파일인가 (스크립트면 실제로 열어서 무엇을
   계산·검증하는지, 데이터 파일이면 어떤 스크립트의 산출물로 보이는지)
2  최신 여부 — 이 내용이 다른 어딘가(docs/verification/·docs/control/·이미 커밋된
   research/strategy-lab/reports/·CLAUDE.md)에 이미 반영·대체됐는가? 대체됐다면
   그 증거(어느 문서의 어느 줄)를 인용하라. 증거 없이 "아마 오래됐을 것"이라고
   추정하지 마라 — 모르면 "미확인"이라고 써라
3  production 영향 — lib/·scripts/·config/를 실제로 건드렸는지 grep으로 확인
   (읽기만 한 진단 스크립트인지, production 파일을 수정한 흔적이 있는지)
4  cross-reference — 이 파일명이 docs/control/의 인수인계 문서들(특히
   세션인수인계-2026-08-17.md·-18.md·-18-b.md·-19.md·-20.md)에서 언급되는지 grep해서
   확인하라. 언급된 맥락(예: "이 스크립트로 확인한 결과...")이 있으면 그 인수인계가
   가리키는 결론이 이미 다른 곳(리포트·CLAUDE.md)에 정착됐는지도 같이 확인해라
5  파일 쌍 추정 — .json/.txt 데이터 파일은 같은 이름 패턴의 .py 스크립트가 만들었을
   가능성이 있다(예: corp_action_analysis.json ↔ check_corp_action.py). 짝을
   추정할 수 있으면 명시하고, 스크립트 없이 데이터만 있으면 그것도 적어라
6  추천 라벨 — 다음 넷 중 하나
   커밋 추천        내용이 검증 가능하고 최신이며 production 무변경
   보류(최신본 있음)  더 새 버전/대체 문서가 있다 — 그 근거를 반드시 적어라
   보류(불확실)      판단 근거 부족 — 왜 판단이 안 되는지 적어라
   삭제 후보         진짜 임시 스크래치(디버그 print문, 1회성 실험, 빈 파일)로
                    보이고 어디서도 참조 안 됨 — 단, 삭제는 제안만, 실행은 절대 금지
```

## 하지 말 것

```
✗ 저장소에 어떤 파일도 쓰지 마세요(진짜 읽기 전용) — git add/commit/rm 전부 금지
✗ production 코드(lib/·scripts/·config/) 수정 금지
✗ "이건 지워도 됩니다"를 확정으로 말하지 마세요 — 삭제는 항상 사람 승인이 필요한
  별도 결정이다(이 저장소 규칙). 후보 표시만 하라
✗ 파일명만 보고 넘기지 마세요 — 특히 temp_*·verify_*류도 실제로 열어서 무엇을
  검증했는지 읽어라. "temp"라는 이름이 곧 삭제 후보를 뜻하지 않는다
```

## 산출 형식

표 하나, 컬럼: 파일 | 한 줄 요약 | 최신 여부(근거) | production 영향 |
인수인계 언급 여부 | 추천 라벨

마지막에:
```
## 특히 확인된 것 (중요도 순, 최대 5개)
## 확인 / 추정 / 미확인
```

## 결과 전달

대화로 Claude에게 전달하면, Claude가 라벨별로 최종 커밋 여부를 판단하고 실제
git add/commit을 실행한다. 이 과제 자체는 그 판단의 재료만 만든다.
