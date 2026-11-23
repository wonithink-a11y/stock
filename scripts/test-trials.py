"""research/strategy-lab/trials.py selftest 를 회귀에 묶는다(네트워크 없음)."""
import importlib.util, pathlib
p = pathlib.Path(__file__).resolve().parent.parent / "research" / "strategy-lab" / "trials.py"
s = importlib.util.spec_from_file_location("trials", p); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
m.selftest()
