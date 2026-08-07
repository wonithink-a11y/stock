#!/usr/bin/env python3
"""샤드별로 가장 진행된 시도를 골라 _shards/에 놓는다.

  python scripts/pick-shard-artifacts.py <아티팩트 루트> <목적지>

재실행이 있으면 한 샤드에 여러 시도의 아티팩트가 생긴다(a3-shard-7-a1, -a2 …).
셋을 합치면 안 된다 — 같은 파일명을 담고 있어 **추출 순서가 승자를 정하고**, 그것은
비결정적이며 진행이 덜 된 시도가 이길 수 있다(교훈62의 다음 얼굴이다).

**'나중 것'이 아니라 '더 나아간 것'을 고른다.** 상태는 단조 축적이고 모든 시도가
같은 커밋 상태에서 출발하므로, corpsDone이 많은 쪽이 적은 쪽을 포함한다 —
todo 순서가 sorted(corps)로 결정적이라 덜 돈 시도는 더 돈 시도의 앞부분이다.

세 파일을 **한 시도에서 통째로** 가져온다. 상태만 A에서, jsonl은 B에서 가져오면
상태가 완료라고 말하는 법인의 레코드가 없을 수 있다 — save_progress가 셋을 함께
쓰는 이유가 그것이고, 여기서 갈라 오면 그 보장이 깨진다.

의존성 없이 표준 라이브러리만 쓴다. persist 잡에는 pip install이 없다.
"""
import glob
import json
import os
import re
import shutil
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(errors="replace")

# a3-shard-<N>-a<시도>. 시도 번호가 없는 옛 이름(a3-shard-<N>)도 받는다 —
# 이름 규칙을 바꾸기 전에 올라간 아티팩트가 섞일 수 있고, 거부하면 그 진행을 잃는다.
NAME_RE = re.compile(r"^a3-shard-(\d+)(?:-a(\d+))?$")


def shard_of(dirname):
    m = NAME_RE.match(dirname)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2) or 1)


def rank(state_path):
    """고르는 기준 (corpsDone 수, recordGaps 법인 수). 큰 쪽이 이긴다.

    1순위는 진행이다. 2순위가 필요한 이유는 **진행이 같은데 사실이 더 많은 상태가
    있기** 때문이다 — 실측: 샤드 6은 어제와 오늘 실행이 같은 346법인에서 멈췄고
    corpsDone 집합도 레코드 수도 완전히 같았는데, 오늘 것에만 recordGaps 94법인이
    있었다(그 필드를 그 사이에 넣었다). 동점을 '건너뜀'으로 처리하면 그 94법인의
    공백 사유가 사라지고, 그것은 **재수집 없이는 영영 못 얻는 사실이다**(교훈75).

    읽을 수 없으면 (-1, -1) — 깨진 상태가 온전한 것을 이기면 안 된다.
    """
    try:
        with open(state_path, encoding="utf-8") as f:
            st = json.load(f)
        return (len(st.get("corpsDone") or []), len(st.get("recordGaps") or {}))
    except Exception:
        return (-1, -1)


def done_count(state_path):
    return rank(state_path)[0]


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    root, dest = sys.argv[1], sys.argv[2]
    if not os.path.isdir(root):
        print(f"{root} 없음 — 다운로드 스텝이 아무것도 받지 못했다")
        return 1
    os.makedirs(dest, exist_ok=True)

    # 목적지에 이미 있는 상태도 후보다. 이것이 없으면 **회수가 역행할 수 있다** —
    # 어제 아티팩트로 샤드 6을 346까지 올려둔 뒤 오늘 아티팩트(341)를 회수하면
    # 175법인이 사라진다. 아티팩트끼리만 비교하면 그 경로가 열린 채로 남는다.
    # 상태는 단조 축적이므로 '이미 있는 것보다 뒤로 가지 않는다'가 불변식이다.
    floor = {}
    for p in glob.glob(os.path.join(dest, "_state-*.json")):
        m = re.search(r"_state-(\d+)\.json$", os.path.basename(p))
        if m:
            floor[int(m.group(1))] = rank(p)

    # shard -> (done, attempt, dir)
    best = {}
    seen = 0
    for d in sorted(os.listdir(root)):
        full = os.path.join(root, d)
        if not os.path.isdir(full):
            continue
        shard, attempt = shard_of(d)
        if shard is None:
            print(f"  건너뜀 (이름 규칙 밖) {d}")
            continue
        seen += 1
        st = os.path.join(full, f"_state-{shard}.json")
        n = rank(st) if os.path.exists(st) else (-1, -1)
        cur = best.get(shard)
        # 순위가 같으면 나중 시도를 쓴다. 진행도 사실도 같다면 최신 진단이 더 유용하다.
        if cur is None or (n, attempt) > (cur[0], cur[1]):
            best[shard] = (n, attempt, full)

    if not best:
        print(f"고를 샤드가 없다 (아티팩트 디렉터리 {seen}개) — 이름 규칙을 확인한다")
        return 1

    for shard in sorted(best):
        n, attempt, src = best[shard]
        if n[0] < 0:
            print(f"  샤드 {shard}: 상태 파일을 읽을 수 없다 ({os.path.basename(src)}) — 건너뛴다")
            continue
        have = floor.get(shard)
        if have is not None and n <= have:
            # 순위가 같거나 낮으면 쓰지 않는다. 순위는 (진행, 사실의 양)이라
            # '진행은 같은데 사실이 더 많은' 후보는 여기서 걸리지 않고 통과한다.
            verdict = "동일" if n == have else f"역행 {have}→{n}"
            print(f"  샤드 {shard}: 목적지가 이미 (done {have[0]}, gaps {have[1]}) — 건너뛴다 ({verdict})")
            continue
        # 셋을 한 시도에서 통째로 가져온다. 갈라 오면 상태와 산출물이 어긋난다.
        moved = []
        for name in (f"_state-{shard}.json", f"shard-{shard}.jsonl",
                     f"_diagnostics-shard-{shard}.json"):
            p = os.path.join(src, name)
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(dest, name))
                moved.append(name)
        print(f"  샤드 {shard}: 시도 a{attempt} 채택 (done {n[0]} · gaps {n[1]}) · 파일 {len(moved)}개")

    # 어느 시도가 졌는지 남긴다. 사람이 나중에 "왜 이 상태인가"를 물을 때의 근거다.
    for shard in sorted(best):
        cands = []
        for d in sorted(os.listdir(root)):
            s, a = shard_of(d)
            if s == shard:
                cands.append((a, rank(os.path.join(root, d, f"_state-{s}.json"))))
        if len(cands) > 1:
            desc = " · ".join(f"a{a}:done {n[0]}/gaps {n[1]}" for a, n in sorted(cands))
            print(f"  샤드 {shard} 후보 {len(cands)}개 — {desc}")
    print(f"완료 — 샤드 {len(best)}개를 {dest}에 놓았다")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
