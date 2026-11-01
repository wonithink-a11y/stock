#!/usr/bin/env python3
"""forecast_screen.py 계산 함수(분기 비교·4분기 합·갈래 문턱) — 네트워크 없이."""
import subprocess, sys
from pathlib import Path
r = subprocess.run([sys.executable, str(Path(__file__).resolve().parent.parent / "research/strategy-lab/forecast_screen.py"), "--selftest"],
                   capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
print("test-forecast-screen OK")
