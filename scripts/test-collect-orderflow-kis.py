"""collect-orderflow-kis.py 자체 시험(네트워크 없음) — 회귀 자동 발견용 껍데기."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("of", Path(__file__).resolve().parent / "collect-orderflow-kis.py")
of = importlib.util.module_from_spec(spec)
spec.loader.exec_module(of)
of.selftest()
