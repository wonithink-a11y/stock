"""Restart-safe paper-trading position state - one JSON file per strategy under
research/strategy-lab/data/paper/. This is live mutable state, not a research
finding or a backfill artifact - data/backfill/ rule 4 does not apply here, but
by the same logic this directory is not meant to be committed either (added to
.gitignore alongside it). A crash or restart between runs must not lose a
PENDING_ENTRY or OPEN position - that is the entire point of writing it to disk
after every run_once() call instead of keeping it only in memory.
"""
import json
from pathlib import Path

STATE_DIR = "research/strategy-lab/data/paper"


def _path(repo_root, strategy_id):
    return Path(repo_root) / STATE_DIR / f"{strategy_id}_positions.json"


def load(repo_root, strategy_id):
    p = _path(repo_root, strategy_id)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(repo_root, strategy_id, positions):
    p = _path(repo_root, strategy_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(positions, f, ensure_ascii=False, indent=2)
