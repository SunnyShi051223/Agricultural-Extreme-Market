import numpy as np
import pandas as pd

from extreme_market.continuous import build_continuous_series


def _panel():
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    rows = []
    for day, first_close, second_close, first_oi, second_oi in zip(
        dates,
        [100, 101, 102, 103, 104],
        [100, 101, 102, 110, 111],
        [100, 100, 90, 80, 80],
        [90, 90, 95, 120, 130],
    ):
        for code, close, oi in (("M2401", first_close, first_oi), ("M2405", second_close, second_oi)):
            rows.append({"trade_date": day, "contract_code": code, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 10, "open_interest": oi, "settlement": close, "source": "test"})
    return pd.DataFrame(rows)


def test_roll_requires_two_sessions_and_applies_same_day_ratio():
    continuous, rolls = build_continuous_series(_panel(), dominance_sessions=2)
    assert continuous.active_contract.tolist() == ["M2401", "M2401", "M2401", "M2401", "M2405"]
    assert len(rolls) == 1
    assert rolls.iloc[0].adjustment_status == "same_session_ratio_applied"
    assert np.isclose(continuous.iloc[2].adjusted_close, 102 * (104 / 111))
    assert np.isclose(continuous.iloc[-1].adjusted_close, 111)


def test_raw_and_adjusted_returns_are_retained():
    continuous, _ = build_continuous_series(_panel(), dominance_sessions=2)
    assert "raw_close_return_1d" in continuous
    assert "adjusted_close_return_1d" in continuous
