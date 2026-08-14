"""The Strategy contract every strategies/<id>/rule.py module must satisfy.

This is a documentation/typing contract, not a class hierarchy - runner.py loads
a strategy module by path (importlib, since directory names may not always be
valid package identifiers) and calls these four names directly. A Protocol is
used only so a type checker (or a human) can see the required shape in one place;
nothing here executes.

Required module-level names in strategies/<id>/rule.py:

    PARAMS: dict                 loaded from the sibling policy.json

    compute_features(bars: pd.DataFrame) -> pd.DataFrame
        Vectorized, causal-only indicator computation. Adds indicator columns to
        a copy of bars. Must not use any row beyond the row being computed.

    generate_signals(symbol: str, features: pd.DataFrame) -> list[Signal]
        Bulk signal detection over the whole (already-causal) feature frame.

    risk_spec_for(features_row) -> RiskSpec
        Resolves stop/target sizing from data available at the signal row only
        (e.g. ATR[t]) - never from later rows.

    evaluate_at(pit_features: PITBars, symbol: str, date: str, prev_date: str) -> Signal | None
        The same signal logic as generate_signals, but PIT-guarded per date via
        pit_features.at() (raises PITViolation if date is beyond as_of) - used by
        the PIT-violation unit test, not by the bulk smoke run (which uses
        generate_signals for speed; both apply the identical boolean formula).

    TIE_BREAK: str                name registered in engine.portfolio.tieBreak
"""
from typing import Protocol

import pandas as pd

from engine.signals.schema import RiskSpec, Signal


class Strategy(Protocol):
    PARAMS: dict
    TIE_BREAK: str

    def compute_features(self, bars: pd.DataFrame) -> pd.DataFrame: ...
    def generate_signals(self, symbol: str, features: pd.DataFrame) -> list[Signal]: ...
    def risk_spec_for(self, features_row) -> RiskSpec: ...
    def evaluate_at(self, pit_features, symbol: str, date: str, prev_date: str) -> "Signal | None": ...
