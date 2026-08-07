#!/usr/bin/env python3
"""샤드 아티팩트 선택기 회귀 — 어느 시도가 살아남는가.
  python scripts/test-pick-artifacts.py

이 선택이 틀리면 하루치 수집이 조용히 사라진다. 덜 진행한 시도가 이겨도 상태는
정상으로 보이고(단조 축적이라 항등식도 다 맞는다) 아무도 모른다.
"""
import importlib.util
import json
import os
import shutil
import sys
import tempfile

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location(
    "pick", os.path.join(ROOT, "scripts", "pick-shard-artifacts.py"))
pick = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pick)

passed = failed = 0


def ok(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  OK    {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}{('  — ' + detail) if detail else ''}")


def make(root, artifact, shard, done, rows=1, broken=False):
    d = os.path.join(root, artifact)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(d, f"_state-{shard}.json")
    if broken:
        open(p, "w", encoding="utf-8").write("{ not json")
    else:
        json.dump({"shard": shard, "corpsDone": [f"{i:08d}" for i in range(done)],
                   "hardSkipped": {}},
                  open(p, "w", encoding="utf-8"))
    with open(os.path.join(d, f"shard-{shard}.jsonl"), "w", encoding="utf-8") as f:
        for i in range(rows):
            f.write(json.dumps({"corp": f"{i:08d}", "attempt": artifact}) + "\n")
    json.dump({"shard": shard, "from": artifact},
              open(os.path.join(d, f"_diagnostics-shard-{shard}.json"), "w",
                   encoding="utf-8"))
    return d


def run(root, dest):
    argv = sys.argv
    sys.argv = ["pick", root, dest]
    try:
        return pick.main()
    finally:
        sys.argv = argv


def state_done(dest, shard):
    with open(os.path.join(dest, f"_state-{shard}.json"), encoding="utf-8") as f:
        return len(json.load(f)["corpsDone"])


def jsonl_from(dest, shard):
    with open(os.path.join(dest, f"shard-{shard}.jsonl"), encoding="utf-8") as f:
        return json.loads(f.readline())["attempt"]


print("[더 나아간 시도가 이긴다]")
tmp = tempfile.mkdtemp()
try:
    root, dest = os.path.join(tmp, "art"), os.path.join(tmp, "out")
    # 재실행이 덜 진행한 경우 — overwrite였다면 여기서 2법인을 잃었다.
    make(root, "a3-shard-7-a1", 7, done=350)
    make(root, "a3-shard-7-a2", 7, done=348)
    ok("선택기가 정상 종료한다", run(root, dest) == 0)
    ok("나중 시도가 덜 진행했으면 앞 시도를 쓴다 (나중 것이 아니라 나아간 것)",
       state_done(dest, 7) == 350, str(state_done(dest, 7)))
    ok("jsonl도 같은 시도에서 온다 (상태와 산출물을 갈라 오지 않는다)",
       jsonl_from(dest, 7) == "a3-shard-7-a1", jsonl_from(dest, 7))
    with open(os.path.join(dest, "_diagnostics-shard-7.json"), encoding="utf-8") as f:
        ok("진단도 같은 시도에서 온다",
           json.load(f)["from"] == "a3-shard-7-a1")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n[재실행이 더 나아간 경우]")
tmp = tempfile.mkdtemp()
try:
    root, dest = os.path.join(tmp, "art"), os.path.join(tmp, "out")
    make(root, "a3-shard-3-a1", 3, done=100)
    make(root, "a3-shard-3-a2", 3, done=140)
    run(root, dest)
    ok("재실행이 더 나아갔으면 재실행을 쓴다", state_done(dest, 3) == 140)
    ok("그때도 파일 셋이 같은 시도에서 온다",
       jsonl_from(dest, 3) == "a3-shard-3-a2")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n[샤드 간 격리 — 교훈62의 범위 규칙]")
tmp = tempfile.mkdtemp()
try:
    root, dest = os.path.join(tmp, "art"), os.path.join(tmp, "out")
    for s in range(3):
        make(root, f"a3-shard-{s}-a1", s, done=10 * (s + 1))
    make(root, "a3-shard-1-a2", 1, done=5)      # 샤드 1만 재실행, 덜 진행
    run(root, dest)
    ok("샤드마다 독립적으로 고른다",
       state_done(dest, 0) == 10 and state_done(dest, 2) == 30,
       f"{state_done(dest, 0)} {state_done(dest, 2)}")
    ok("한 샤드의 재실행이 다른 샤드를 건드리지 않는다",
       state_done(dest, 1) == 20, str(state_done(dest, 1)))
    ok("샤드 수만큼 파일이 놓인다",
       len([f for f in os.listdir(dest) if f.startswith("_state-")]) == 3,
       str(sorted(os.listdir(dest))))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n[깨진 후보와 옛 이름]")
tmp = tempfile.mkdtemp()
try:
    root, dest = os.path.join(tmp, "art"), os.path.join(tmp, "out")
    make(root, "a3-shard-5-a1", 5, done=200)
    make(root, "a3-shard-5-a2", 5, done=0, broken=True)
    run(root, dest)
    ok("읽을 수 없는 상태는 온전한 것을 이기지 못한다",
       state_done(dest, 5) == 200, str(state_done(dest, 5)))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

tmp = tempfile.mkdtemp()
try:
    root, dest = os.path.join(tmp, "art"), os.path.join(tmp, "out")
    # 이름 규칙을 바꾸기 전에 올라간 아티팩트. 거부하면 그 진행을 잃는다.
    make(root, "a3-shard-4", 4, done=77)
    ok("시도 번호 없는 옛 이름도 받는다", run(root, dest) == 0)
    ok("옛 이름의 진행이 살아난다", state_done(dest, 4) == 77)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

tmp = tempfile.mkdtemp()
try:
    root, dest = os.path.join(tmp, "art"), os.path.join(tmp, "out")
    os.makedirs(os.path.join(root, "some-other-artifact"), exist_ok=True)
    ok("고를 것이 없으면 실패로 끝난다 (조용히 0개를 놓지 않는다)",
       run(root, dest) == 1)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n[목적지보다 뒤로 가지 않는다]")
# 회수는 여러 번에 걸쳐 일어난다. 어제 아티팩트로 샤드 6을 346까지 올려둔 뒤
# 오늘 아티팩트(341)를 회수하면 175법인이 사라진다 — 아티팩트끼리만 비교하면
# 그 경로가 열린 채로 남는다. 상태는 단조 축적이므로 목적지도 후보다.
tmp = tempfile.mkdtemp()
try:
    root, dest = os.path.join(tmp, "art"), os.path.join(tmp, "out")
    make(root, "a3-shard-6-a1", 6, done=346)
    run(root, dest)
    ok("1차 회수는 그대로 들어간다", state_done(dest, 6) == 346)

    root2 = os.path.join(tmp, "art2")
    make(root2, "a3-shard-6-a1", 6, done=341)
    run(root2, dest)
    ok("나중 회수가 덜 진행했으면 목적지를 지키지 않는다 (역행 금지)",
       state_done(dest, 6) == 346, str(state_done(dest, 6)))

    root3 = os.path.join(tmp, "art3")
    make(root3, "a3-shard-6-a1", 6, done=470)
    run(root3, dest)
    ok("나중 회수가 더 진행했으면 갱신한다", state_done(dest, 6) == 470)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n[아티팩트에 남의 샤드 파일이 섞여 있어도]")
# 실측: collect #2의 아티팩트는 8샤드 파일을 전부 담고 있었다(경로 지정 전 버전).
# 폴더 이름이 지목하는 샤드의 파일만 봐야 남의 옛 상태를 끌어오지 않는다.
tmp = tempfile.mkdtemp()
try:
    root, dest = os.path.join(tmp, "art"), os.path.join(tmp, "out")
    d = make(root, "a3-shard-2-a1", 2, done=349)
    make(root, "a3-shard-2-a1", 5, done=99)      # 같은 폴더에 남의 샤드 파일
    run(root, dest)
    ok("폴더가 지목하는 샤드만 채택한다", state_done(dest, 2) == 349)
    ok("같은 폴더의 남의 샤드는 놓지 않는다",
       not os.path.exists(os.path.join(dest, "_state-5.json")),
       str(sorted(os.listdir(dest))))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\n[의존성]")
src = open(os.path.join(ROOT, "scripts/pick-shard-artifacts.py"), encoding="utf-8").read()
ok("서드파티를 import하지 않는다 (persist 잡에 pip install이 없다)",
   "requests" not in src and "pandas" not in src)

print("\n[워크플로 배선]")
wf_raw = open(os.path.join(ROOT, ".github/workflows/fundamentals-a3.yml"),
              encoding="utf-8").read()
# 주석을 걷어내고 본다. 이 워크플로의 주석은 '왜 안 쓰는가'를 길게 적어두므로,
# 원문을 그대로 grep하면 설명문에 걸려 설정이 있는 것처럼 읽힌다.
# YAML 파서는 쓰지 않는다 — 이 테스트가 도는 잡은 pip install을 하지 않는다.
wf = "\n".join(l for l in wf_raw.splitlines() if not l.lstrip().startswith("#"))

ok("아티팩트 이름에 시도 번호가 들어간다 (409를 이름으로 피한다)",
   "run_attempt }}" in wf and "a3-shard-${{ matrix.shard }}-a" in wf)
ok("merge-multiple을 설정하지 않는다 (추출 순서가 승자를 정하면 안 된다)",
   "merge-multiple" not in wf, "설정에 남아 있다")
ok("선택기를 커밋 전에 부른다",
   wf.index("pick-shard-artifacts.py") < wf.index("Commit progress"))
ok("overwrite로 덮지 않는다 (더 나아간 시도를 지울 수 있다)",
   "overwrite: true" not in wf, "설정에 남아 있다")

print(f"\n{'=' * 54}")
print(f"통과 {passed} · 실패 {failed}")
sys.exit(0 if failed == 0 else 1)
