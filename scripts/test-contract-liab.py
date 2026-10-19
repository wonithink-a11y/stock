#!/usr/bin/env python3
"""build-contract-liab.py 의 순수 계산(사업연도 고르기·조회 계획·dCL·순위) 회귀 — 네트워크 없음."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("build_contract_liab", Path(__file__).resolve().parent / "build-contract-liab.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.selftest()
