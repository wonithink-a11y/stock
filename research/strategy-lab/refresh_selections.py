#!/usr/bin/env python
"""라이브 페이퍼 슬리브의 selection.json 을 한 번에 재생성한다.

왜 있나
-------
페이퍼 엔진은 selection.json 에 **그 리밸런싱일이 있어야만** 움직인다. 없으면
run_monthly_rebalance.py 가 poll_once 를 부르기 전에 return 하고, 신규매수뿐
아니라 **청산·체결확인까지 전부 멈춘다**(로그는 정상처럼 보인다). 그런데 이
갱신이 지금까지 손으로만 됐고, 손으로 하려면 다섯 스크립트의 실행 순서를
기억해야 했다. 그 순서를 여기 한 곳에 적어 자동화가 부를 수 있게 한다.

의존 순서 (지켜야 한다)
-----------------------
  1. valuation-panel        (node)  - pbr 계열 전부의 입력
  2. pbr_value_v1
  3. pbr_value_v1_dropout           - combined 의 baseline
  4. pbr_value_v1_combined          - period 를 baseline 에서 읽는다(3 다음이어야 함)
  5. lowmom60_v1
  6. factor_earnings_yield_v1
  7. foreign_flow5d_v1              - 일별. 다른 것과 무관하지만 같이 돌린다

기준일
------
--end 를 안 주면 각 빌더가 캘린더의 마지막 거래일을 스스로 쓴다
(_default_end). 기준일을 여기서 계산해 넘기지 않는 이유는, 그러면 이 파일이
또 하나의 "박힌 날짜" 후보가 되기 때문이다.

사용법
------
  python refresh_selections.py --dry-run     실행할 명령만 출력
  python refresh_selections.py               전부 재생성
  python refresh_selections.py --end 2026-10-01
"""
import argparse
import json
import os
import subprocess
import sys
import time

_THIS = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(os.path.dirname(_THIS))

# (라벨, 실행기, 스크립트경로(REPO_ROOT 기준), --end 를 받는가)
STEPS = [
    ("valuation-panel", "node", "scripts/build-a5-valuation-panel.js", True),
    ("pbr_value_v1", "python", "research/strategy-lab/strategies/pbr_value_v1/build_selection.py", True),
    ("pbr_value_v1_dropout", "python",
     "research/strategy-lab/strategies/pbr_value_v1_dropout/build_selection_dropout.py", True),
    ("pbr_value_v1_combined", "python",
     "research/strategy-lab/strategies/pbr_value_v1_combined/build_selection_combined.py", False),
    ("lowmom60_v1", "python", "research/strategy-lab/strategies/lowmom60_v1/build_selection.py", True),
    # ★ build_factor_selection.py 는 research/strategy-lab/data/a4/의 파생 데이터셋
    # (958MB, gitignore 대상)을 읽는다. 저장소에 없으므로 CI 에서는 먼저 만들어야
    # 한다 - 로컬에는 이미 있어서 이 의존이 안 보였고, CI 4회차에서 드러났다
    # (FileNotFoundError: a4-research-dataset.parquet).
    ("a4-research-dataset", "python", "research/strategy-lab/build_a4_research_dataset.py", False),
    ("factor_earnings_yield_v1", "python", "research/strategy-lab/build_factor_selection.py", True),
    ("foreign_flow5d_v1", "python",
     "research/strategy-lab/strategies/foreign_flow5d_v1/build_selection.py", True),
]

# 라이브 슬리브의 selection.json - 갱신 후 이 파일들이 "이번 리밸런싱일"을
# 갖고 있는지 확인한다. 갖고 있지 않으면 실패로 만든다.
LIVE_SELECTIONS = {
    "pbr_value_v1": "research/strategy-lab/strategies/pbr_value_v1/selection.json",
    "lowmom60_v1": "research/strategy-lab/strategies/lowmom60_v1/selection.json",
    "pbr_value_v1_combined": "research/strategy-lab/strategies/pbr_value_v1_combined/selection.json",
    "factor_earnings_yield_v1": "research/strategy-lab/strategies/factor_earnings_yield_v1/selection.json",
    "foreign_flow5d_v1": "research/strategy-lab/strategies/foreign_flow5d_v1/selection.json",
}


# 체인이 실제로 쓰는 서드파티. pyarrow 는 **import 문에 안 나온다** - pandas 의
# to_parquet 이 런타임에 찾는 엔진이라(engine/data/a2aProvider.py 가 일봉을
# parquet 로 캐시한다) 정적 스캔으로는 절대 안 잡힌다. 실제로 CI 에서 의존성을
# 한 번에 하나씩 발견하며 세 번 실패했다(pytest -> pyarrow -> scipy).
# 여기 한 줄로 모아 두고 --check-deps 로 먼저 확인한다.
REQUIRED_IMPORTS = ["pandas", "numpy", "scipy", "pyarrow"]


def check_deps(out=print):
    import importlib
    missing = []
    for m in REQUIRED_IMPORTS:
        try:
            importlib.import_module(m)
            out(f"  {m:<10} OK")
        except ImportError as e:
            missing.append(m)
            out(f"  {m:<10} 없음 - {e}")
    if missing:
        out("\n★ 빠진 의존성: " + " ".join(missing))
        out("   pip install " + " ".join(missing))
    return missing


def calendar_last_session():
    with open(os.path.join(REPO_ROOT, "data", "backfill", "calendar.json"), encoding="utf-8") as f:
        return json.load(f)["tradingDays"][-1]


def this_month_rebalance_date(last_session):
    """캘린더에서 그 달의 첫 거래일. 월간 슬리브가 쓰는 as_of 다."""
    with open(os.path.join(REPO_ROOT, "data", "backfill", "calendar.json"), encoding="utf-8") as f:
        days = json.load(f)["tradingDays"]
    ym = last_session[:7]
    same = [d for d in days if d[:7] == ym]
    return same[0] if same else None


def selection_dates(rel_path):
    with open(os.path.join(REPO_ROOT, rel_path), encoding="utf-8") as f:
        d = json.load(f)
    out = set()
    for entries in d["selection"].values():
        for e in entries:
            out.add(e["date"])
    return out


def verify(expect_month_date, out=print):
    """★ 갱신이 '돌았다'와 '이번 달을 만들었다'는 다른 말이다. 빌더가 조용히
    과거까지만 만들어도 종료코드는 0 이다(2026-09-09 실측 - 박힌 기본 END 로
    라이브 달이 통째로 빠진 파일이 정상 종료로 생성됐다). 그래서 산출물을
    직접 읽어 확인한다(교훈43 - 통과했다는 증명은 따로 해야 한다)."""
    bad = []
    for sid, rel in LIVE_SELECTIONS.items():
        dates = selection_dates(rel)
        newest = max(dates) if dates else None
        if sid == "foreign_flow5d_v1":
            # 일별 - '이번 달 첫 거래일'이 아니라 '최근 것이 있나'를 본다
            ok = newest is not None and newest >= expect_month_date
        else:
            ok = expect_month_date in dates
        out(f"  {sid:<26} 최신 {newest}  {'OK' if ok else '★ 이번 리밸런싱일 없음'}")
        if not ok:
            bad.append(sid)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--end", default=None, help="기준일. 생략하면 각 빌더가 캘린더 마지막 거래일을 쓴다")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--check-deps", action="store_true",
                     help="체인이 쓰는 서드파티가 다 있는지만 확인하고 끝낸다")
    ap.add_argument("--only", default=None, help="쉼표로 구분한 라벨만 실행(디버깅용)")
    args = ap.parse_args()

    if args.check_deps:
        return 1 if check_deps() else 0

    last = calendar_last_session()
    month_date = this_month_rebalance_date(last)
    print(f"캘린더 마지막 거래일 {last} · 이번 달 리밸런싱일 {month_date}")

    only = set(args.only.split(",")) if args.only else None
    t0 = time.time()
    for label, runner, rel, takes_end in STEPS:
        if only and label not in only:
            continue
        if label == "a4-research-dataset" and os.path.exists(os.path.join(
                REPO_ROOT, "research", "strategy-lab", "data", "a4",
                "a4-research-dataset.parquet")):
            print(f"\n=== {label} ===\n"
                  "  이미 있음 - 건너뜀(958MB). 원자료가 바뀌면 지우고 다시 돌린다.")
            continue
        exe = sys.executable if runner == "python" else "node"
        cmd = [exe, os.path.join(REPO_ROOT, rel)]
        if takes_end and args.end:
            cmd += ["--end", args.end]
        print(f"\n=== {label} ===\n  {' '.join(cmd[1:])}")
        if args.dry_run:
            continue
        r = subprocess.run(cmd, cwd=REPO_ROOT)
        if r.returncode != 0:
            # 여기서 멈춘다 - 뒤 단계가 앞 단계 산출물을 읽으므로(combined <- dropout)
            # 실패를 물고 계속 가면 조용히 낡은 baseline 으로 만든다.
            print(f"[중단] {label} 실패(exit {r.returncode}) - 뒤 단계는 앞 산출물에 의존한다")
            return 1

    if args.dry_run:
        print("\n[dry-run] 아무 것도 실행하지 않았다.")
        return 0

    print(f"\n=== 확인 ({time.time()-t0:.0f}s) ===")
    bad = verify(month_date)
    if bad:
        print(f"\n★ 실패: {bad} 에 이번 리밸런싱일({month_date})이 없다. "
              f"커밋하면 페이퍼 엔진이 그 슬리브에서 멈춘다.")
        return 1
    print("\n전부 이번 리밸런싱일을 갖고 있다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
