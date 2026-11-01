#!/usr/bin/env python3
"""VI forward 기록·판정 시점 거부(run_kr_static_vi_forward --selftest) — 네트워크·분봉 없이."""
import subprocess, sys
from pathlib import Path
r = subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "research/strategy-lab/run_kr_static_vi_forward.py"), "--selftest"],
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
print("test-vi-forward OK")
