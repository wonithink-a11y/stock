"""Rule Discovery Lab 대시보드용 로컬 서버.

python -m http.server와 거의 같지만, 대시보드가 /findings/_registry.jsonl을
요청할 때마다 findings/ 디렉터리를 다시 스캔해서 파일을 새로 쓴 뒤 서빙한다.
그래야 새 finding이 생겼을 때 수동으로 build_findings_registry.py를 다시
돌리지 않아도 대시보드의 10초 폴링이 실제로 최신 상태를 본다.

사용법 (research/strategy-lab에서, 또는 어디서든 - 경로는 __file__ 기준):
  python dashboard/serve.py [--port 8732]
"""
import argparse
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build_findings_registry import build_registry, write_registry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FINDINGS_DIR = ROOT / "findings"
REGISTRY_PATH = FINDINGS_DIR / "_registry.jsonl"


class LiveRegistryHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/findings/_registry.jsonl":
            write_registry(build_registry(FINDINGS_DIR), REGISTRY_PATH)
        super().do_GET()

    def guess_type(self, path):
        # 기본 SimpleHTTPRequestHandler는 .md/.json에 charset을 안 붙여서
        # 브라우저가 시스템 로캘(Windows면 cp949 등)로 잘못 추측 - 한글이 깨졌던 원인
        if str(path).endswith(".md"):
            return "text/plain; charset=utf-8"
        if str(path).endswith((".json", ".jsonl")):
            return "application/json; charset=utf-8"
        return super().guess_type(path)

    def log_message(self, fmt, *args):
        pass  # 매 폴링(10초)마다 로그 찍으면 시끄럽다 - 조용히


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8732)
    args = ap.parse_args()
    print(f"Rule Discovery Lab: http://localhost:{args.port}/dashboard/index.html")
    ThreadingHTTPServer(("localhost", args.port), LiveRegistryHandler).serve_forever()


if __name__ == "__main__":
    main()
