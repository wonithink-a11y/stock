#!/usr/bin/env python3
"""vm-status-snapshot 가림·파싱 + research-data status 요약 출력(가짜 스냅샷) — 네트워크·systemd 없이."""
import importlib.util
import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent
r = subprocess.run([sys.executable, str(ROOT / "vm-status-snapshot.py"), "--selftest"], capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr

spec = importlib.util.spec_from_file_location("rd", ROOT / "research-data.py")
rd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rd)
fake = {"host": "stock", "atKST": "2026-11-02 09:10:30", "failed": ["news-alert.service"], "errors": {},
        "timers": {"news-alert.timer": {"ActiveState": "active", "LastTriggerUSec": "Mon 2026-11-02 09:00:01 KST",
                                        "NextElapseUSecRealtime": "Mon 2026-11-02 09:15:00 KST"},
                   "infinite-buying-vts.timer": {"ActiveState": "inactive", "UnitFileState": "disabled"}},
        "services": {"news-alert.service": {"Result": "exit-code", "ExecMainStatus": "1"}},
        "git": {"head": "abc1234 11-02 06:30 msg", "status": []}, "disk": {"freeGB": 50, "totalGB": 100},
        "memMB": {"MemAvailable": 9000, "MemTotal": 9900}, "load": ["0.1", "0.1", "0.1"], "files": {}, "dirCounts": {},
        "journal": {"news-alert.service": ["line a"]}, "logs": {"news-alert": ["log b"]}}


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


rd.http_get = lambda path, key: Resp(json.dumps(fake).encode())
rd.data_key = lambda: "k"
buf = io.StringIO()
with redirect_stdout(buf):
    rd.cmd_status([])
out = buf.getvalue()
assert "failed ['news-alert.service']" in out and "✗ news-alert.service Result=exit-code" in out, out
assert "← inactive/disabled" in out, out
buf = io.StringIO()
with redirect_stdout(buf):
    rd.cmd_status(["news-alert"])
assert "line a" in buf.getvalue() and "log b" in buf.getvalue(), buf.getvalue()
print("test-vm-status OK")
