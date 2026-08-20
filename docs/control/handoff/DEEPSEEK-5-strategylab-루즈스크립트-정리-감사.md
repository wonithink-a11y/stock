# DEEPSEEK-5 — research/strategy-lab 루즈 스크립트·산출물 49개 정리 감사 (분류만, 커밋은 Claude가 함)

```
발행   2026-08-20 · Claude
대상   DeepSeek (읽기 전용 — 분류·요약만 한다. 저장소에 아무것도 쓰지 않는다,
       커밋·삭제·수정 전부 금지)
배경   DEEPSEEK-3(docs/control/handoff/DEEPSEEK-3-미커밋파일-정리-감사.md)은
       research/strategy-lab/reports/ 디렉터리만 다뤘다. strategy-lab 최상위에
       흩어진 .py/.pkl/.txt/.js 루즈 파일은 그 과제 범위에 아예 없었다 — 이 문서가
       처음 다룬다.
핵심   이 파일들 상당수는 **오늘 이미 커밋된 리포트를 만든 생성 스크립트**일
       가능성이 높다(예: lowmom60_survivorship.py → 커밋된
       research/strategy-lab/reports/.../lowmom60_survivorship.json류). 그런
       경우는 재현성을 위해 스크립트도 같이 커밋하는 게 맞다 — 아래 "산출물 대조"
       항목이 이걸 확인하는 절차다. 파일명만 보고 추측하지 말고 실제로 대조해라.
```

## 이미 검토·커밋된 것 (참고용, 다시 볼 필요 없음)

```
research/strategy-lab/data/a4/
research/strategy-lab/reports/2026-08-18-strategy-candidates/
research/strategy-lab/reports/2026-08-16-sl2-sequential/ (요약 7개 파일)
research/strategy-lab/findings/slot-marginal-contribution/
```

## 분류 대상 (research/strategy-lab/ 최상위 루즈 파일, 49개)

```
5dc_v1a_p_resolved.pkl (6.0MB) · analyze_2025_concentration.py ·
analyze_all_years_concentration.py · analyze_long_term_drawdown.py ·
analyze_loss_root_cause.py · analyze_stop_trades.py · audit_integrity.py ·
bar_trade_check.py · breakout_pullback_events.py · cause_decomposition_5dc.py ·
cause_decomposition_part2.py · compute_annual_2154.py ·
compute_annual_from_pickle.py · compute_benchmark_analysis.py ·
compute_benchmark_final.py · compute_ew_benchmark.py ·
compute_ew_benchmark_fast.py · compute_ew_benchmark_fixed.py ·
compute_ew_benchmark_v2.py · debug_equity.py · debug_rev20_diff.py ·
debug_rev20_month.py · full_smoke_result.pkl (★ 667MB — 아래 주의 참고) ·
fusion_analysis_5dc.py · lowmom60_robustness.py · lowmom60_survivorship.py ·
match_baseline_samples.py · method_comparison.py · mfe_result.txt (★ 0바이트,
빈 파일 — 확인만 하고 넘어가라) · output.txt · perf_decomposition.py ·
regime_by_strategy.py · replay_scheduler_5dc.py · rev20_robustness.py ·
run_5dc_v1a_p_merged.py · run_5dc_v1a_p_samebar.py · run_annual_analysis.py ·
sl2_equity_candidates.py · sl2_extract_slim.py · strategy_candidate_backtest.py ·
strategy_candidate_factors.py · strategy_exploration.py ·
strategy_exploration_fast.py · strategy_exploration_fast_results.pkl (20KB) ·
strategy_exploration_optimized.py · test_equity_curve.py · trace_samebar_5dc.py ·
trade_analysis.py · tradingagents_structure_smoke.js · validate_pnl.py ·
yearly_comparison_5dc.py
```

★ `full_smoke_result.pkl`은 667MB다 — 절대 커밋 추천하지 마라. 이 저장소는
GitHub 공개 저장소라 이 크기의 바이너리를 올리면 영구히 저장소 크기에 남는다.
이 파일은 무조건 "삭제 후보"로 분류하되, 어디서 만들어졌는지(생성 스크립트 추정)와
같은 내용을 재현 가능한 더 작은 산출물이 이미 커밋돼 있는지만 확인해라.

## 각 항목마다 확인할 것

```
1  한 줄 요약 — 스크립트면 무엇을 계산/분석하는지, 산출물이면 무엇의 결과인지
2  산출물 대조 — 이 스크립트가 만들었을 법한 파일이 research/strategy-lab/reports/
   아래 이미 커밋된 파일 중에 있는가? 파일명 유사도(예: lowmom60_survivorship.py
   ↔ lowmom60_survivorship.json)뿐 아니라 스크립트를 열어서 실제로 어떤 경로에
   쓰는지(open()·to_json()·to_csv() 등 출력 코드)를 확인해서 근거를 적어라.
   일치하면 "재현성 확보용 커밋 추천" 근거가 된다
3  최신 여부 — CLAUDE.md의 "1,400건 pre-fix 오염분 재확인 전 인용 금지" 목록
   (a25-smoke·b55-smoke·annual-analysis·exit-type-analysis)과 이름이 겹치는
   스크립트가 있으면 그 오염 이슈와 관련 있는지 확인하고 명시해라
4  production 영향 — lib/·scripts/·config/(저장소 루트 기준)를 실제로 건드렸는지
   grep으로 확인. research/strategy-lab은 A2a를 읽기 전용으로만 쓰는 게 설계
   전제다(CLAUDE.md) — 쓰기 시도가 있으면 반드시 지적해라
5  용량 — 개별 파일 5MB 초과면 별도로 강조해라(위 두 .pkl 참고). 대용량 파일이
   다른 문서나 스크립트에서 실제로 로드/참조되는지도 확인해라
6  추천 라벨 — 다음 넷 중 하나
   커밋 추천        내용이 검증 가능하고 최신이며 production 무변경
                    (재현성 확보용 = 이미 커밋된 산출물의 생성 스크립트인 경우 포함)
   보류(최신본 있음)  더 새 버전/대체 스크립트가 있다 — 그 근거를 반드시 적어라
   보류(불확실)      판단 근거 부족 — 왜 판단이 안 되는지 적어라
   삭제 후보         진짜 임시 스크래치/대용량 재생성 캐시로 보이고 어디서도
                    참조 안 됨 — 단, 삭제는 제안만, 실행은 절대 금지
```

## 하지 말 것

```
✗ 저장소에 어떤 파일도 쓰지 마세요(진짜 읽기 전용) — git add/commit/rm 전부 금지
✗ production 코드(lib/·scripts/·config/) 수정 금지
✗ "이건 지워도 됩니다"를 확정으로 말하지 마세요 — 삭제는 항상 사람 승인이 필요한
  별도 결정이다(이 저장소 규칙). 후보 표시만 하라
✗ 파일명 유사도만으로 "재현성 확보용 커밋 추천"을 내지 마세요 — 반드시 스크립트를
  열어서 출력 경로를 확인해라(위 2번)
```

## 산출 형식

표 하나(49행), 컬럼: 파일 | 한 줄 요약 | 산출물 대조(근거) | 최신 여부 |
production 영향 | 용량 특이사항 | 추천 라벨

표가 길면 잘라도 좋다 — 단 자를 경우 어디까지 처리했는지 마지막 줄에 명시하고
"미완료: 나머지 N개는 파일명만 아래 나열"로 남겨서 결과가 유실되지 않게 하라.

마지막에:
```
## 특히 확인된 것 (중요도 순, 최대 5개)
## 확인 / 추정 / 미확인
```

## 결과 전달

대화로 Claude에게 전달하면, Claude가 라벨별로 최종 커밋 여부를 판단하고 실제
git add/commit을 실행한다. 이 과제 자체는 그 판단의 재료만 만든다.
