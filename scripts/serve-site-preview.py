#!/usr/bin/env python3
"""배포 구조(docs/ = 루트, ui/ = /paper-trading/)를 복사 없이 흉내 내어 로컬로 띄운다 — ui 가 ../design/tokens.css 처럼 docs 를 가리켜도 닿게.
    python scripts/serve-site-preview.py [포트=8734]      # 대시보드 http://localhost:8734/ · 모의투자 http://localhost:8734/paper-trading/
읽기 전용 정적 서버(127.0.0.1 만). 저장소 파일은 바꾸지 않는다."""
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCS, UI = ROOT / "docs", ROOT / "ui"


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = unquote(urlsplit(path).path)
        if p == "/paper-trading":
            p = "/paper-trading/"
        base, rel = (UI, p[len("/paper-trading/"):]) if p.startswith("/paper-trading/") else (DOCS, p.lstrip("/"))
        full = (base / rel).resolve()
        if full != base.resolve() and base.resolve() not in full.parents:
            return str(base / "__forbidden__")            # 경로 이탈 차단
        return str(full)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8734
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
