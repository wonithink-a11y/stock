"""trade-odds.py selftest 를 회귀에 묶는다(네트워크 없음)."""
import importlib.util, pathlib
p = pathlib.Path(__file__).with_name("trade-odds.py")
m = importlib.util.spec_from_file_location("trade_odds", p); mod = importlib.util.module_from_spec(m); m.loader.exec_module(mod)
mod.selftest()
