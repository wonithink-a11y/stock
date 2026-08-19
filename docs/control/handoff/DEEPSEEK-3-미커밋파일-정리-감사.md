# DEEPSEEK-3 — 미커밋 파일 전수 정리 감사 (분류만, 커밋은 Claude가 함)

```
발행   2026-08-20 · Claude
대상   DeepSeek (읽기 전용 — 분류·요약만 한다. 저장소에 아무것도 쓰지 않는다,
       커밋·삭제·수정 전부 금지)
선행   오늘 세션에 이미 검토·커밋된 것들(참고용, 다시 볼 필요 없음):
         - research/strategy-lab/data/a4/ (A4 연구 데이터셋)
         - research/strategy-lab/reports/2026-08-18-strategy-candidates/ (REV20 등)
         - docs/verification/SL-2-stop-distance-재현-결과.md +
           research/strategy-lab/reports/2026-08-16-sl2-sequential/ 안의 요약 7개 파일
         - research/strategy-lab/findings/slot-marginal-contribution/ (Codex 발견)
         - docs/verification/DEEPSEEK-2-A4-marginal-IC-결과.md
       이미 보류로 판단해둔 것(다시 볼 필요 없음, 이유만 참고):
         - docs/control/KR-2.3-supplyDemand-설계안.md — 문서 스스로 "Codex 설계
           검토 필요"라고 미결로 남겼고, slot-marginal 발견이 그 우려를 실증함
         - HANDOVER_2026-08-17.md(루트) — 다른 문서가 "구식 문서, same-bar
           231건은 틀렸고 실제 130건"이라고 명시적으로 낡았다고 적어둠
```

## 배경

이 저장소는 같은 날 여러 세션(이 대화·Codex·DeepSeek 등)이 병렬로 작업하는 구조다
(CLAUDE.md「AI 협업 구조」). 오늘(2026-08-19~20) 그렇게 쌓인 미커밋 파일이 많아
Claude가 일부는 검토 후 커밋했지만, 아직 하나도 안 읽어본 것들이 남아 있다.
전부 직접 읽고 판단하면 토큰이 너무 들어서, 1차 분류(읽고 요약 + 최신 여부 +
production 영향 여부)를 위임하고, 최종 커밋 여부는 Claude가 그 요약을 보고 결정한다.

## 분류 대상

### A. 문서 2개
```
docs/control/ChatGPT-세션인수인계-2026-08-17.md
docs/control/세션인수인계-deepseek-2026-08-17.md
```

### B. 상위 reports 디렉터리 (저장소 루트, research/strategy-lab과 다른 경로)
```
reports/2026-08-16-parallel-validation/
```
★ 주의: `research/strategy-lab/reports/2026-08-16-parallel-validation/`(아래 C목록에도
있음)와 **이름이 같은 별개 디렉터리**다. 같은 내용의 중복인지 다른 내용인지
반드시 비교해서 적어라.

### C. research/strategy-lab/reports/ 나머지 20개 (오늘 이미 처리한 3개 제외)
```
2026-08-15-trend-breakout-v1-a25-smoke
2026-08-15-trend-breakout-v1-annual-analysis
2026-08-15-trend-breakout-v1-annual-analysis-2154
2026-08-15-trend-breakout-v1-b55-smoke
2026-08-15-trend-breakout-v1-benchmark-analysis
2026-08-15-trend-breakout-v1-exit-type-analysis
2026-08-15-trend-breakout-v1-smoke
2026-08-15-trend-breakout-v1-smoke-postfix
2026-08-16-parallel-validation
2026-08-16-pnl-equity-validation
2026-08-17-momentum-decile-analysis
2026-08-17-net-margin-decile-analysis
2026-08-17-perf-decomposition
2026-08-17-post-5dc-factor-screening
2026-08-17-postfix-baseline-audit
2026-08-17-postfix-integrity-audit
2026-08-17-survivorship-attribution-design
2026-08-17-survivorship-bias-measurement   (16MB — 안의 큰 파일이 뭔지 특히 확인)
2026-08-17-survivorship-bias-verify-508
2026-08-19-tradingagents-structure-smoke
```

### D. 저장소 루트 스크래치 파일 27개
```
HANDOVER_2026-08-17.md (★ 이미 보류 결정됨, 왜 그런지만 참고하고 다시 판단 안 해도 됨)
analyze_candidates.py · audit_samebar_stop.py · audit_search.py ·
check_corp_action.py · check_data.py · check_excluded.py · check_foreign.py ·
check_foreign2.py · check_pkl.py · classify_impact.py · convert_a2a.py ·
corp_action_analysis.json · final_classification.py · read_files.py ·
same_bar_stops.json · scratch-a4-runbacktest-comparison.json ·
scratch-a4-supplydemand-vertical-slice.json · temp_a4_keys.txt ·
temp_scratch.txt · temp_scratch2.txt · test_load.py · verify_5dc.py ·
verify_a1b_pnl.py · verify_commit.py · verify_survivorship.py · verify_trend.py
```

## 각 항목마다 확인할 것

```
1  한 줄 요약 — 이게 뭘 하는/담고 있는 파일인가
2  최신 여부 — 이 내용이 다른 어딘가(더 최근 문서·CLAUDE.md·이미 커밋된 리포트)에
   이미 반영·대체됐는가? 대체됐다면 그 증거(어느 문서의 어느 줄)를 인용하라.
   증거 없이 "아마 오래됐을 것"이라고 추정하지 마라 — 모르면 "미확인"이라고 써라
3  production 영향 — lib/·scripts/·config/를 실제로 건드렸는지 grep으로 확인
   (읽기만 한 연구 스크립트인지, production 파일을 수정한 흔적이 있는지)
4  용량 — 5MB 넘는 개별 파일이 있으면 따로 적어라(재생성 가능한 원시 캐시일
   가능성이 크다 — .pkl·대용량 .json이 특히 그렇다). 그런 파일이 다른 곳에서
   실제로 인용되는지(다른 문서가 이 파일 경로를 언급하는지)도 확인해라
5  추천 라벨 — 다음 넷 중 하나
   커밋 추천        내용이 검증 가능하고 최신이며 production 무변경
   보류(최신본 있음)  더 새 버전/대체 문서가 있다 — 그 근거를 반드시 적어라
   보류(불확실)      판단 근거 부족 — 왜 판단이 안 되는지 적어라
   삭제 후보         진짜 임시 스크래치(디버그 print문, 1회성 실험)로 보이고
                    어디서도 참조 안 됨 — 단, 삭제는 제안만, 실행은 절대 금지
```

## 하지 말 것

```
✗ 저장소에 어떤 파일도 쓰지 마세요(진짜 읽기 전용) — git add/commit/rm 전부 금지
✗ production 코드(lib/·scripts/·config/) 수정 금지
✗ "이건 지워도 됩니다"를 확정으로 말하지 마세요 — 삭제는 항상 사람 승인이 필요한
  별도 결정이다(이 저장소 규칙). 후보 표시만 하라
✗ 각 파일을 몇 줄 읽고 넘기지 마세요 — 특히 "최신 여부" 판단은 다른 문서와
  실제로 대조해야 한다(파일명·날짜만 보고 추측 금지)
```

## 산출 형식

카테고리(A/B/C/D)별로 표 하나씩, 컬럼: 파일/디렉터리 | 한 줄 요약 | 최신 여부(근거) |
production 영향 | 용량 특이사항 | 추천 라벨

마지막에:
```
## 특히 확인된 것 (중요도 순, 최대 5개)
## 확인 / 추정 / 미확인
```

## 결과 전달

대화로 Claude에게 전달하면, Claude가 라벨별로 최종 커밋 여부를 판단하고 실제
git add/commit을 실행한다. 이 과제 자체는 그 판단의 재료만 만든다.
