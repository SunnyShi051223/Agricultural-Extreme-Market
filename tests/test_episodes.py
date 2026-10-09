import pandas as pd

from extreme_market.episodes import scan_extreme_episodes


def test_tail_scan_merges_same_direction_and_keeps_opposite_overlap():
    dates = pd.date_range("2020-01-01", periods=140, freq="D")
    close = [100.0] * 140
    for index in range(20, 31):
        close[index] = 100 + (index - 19) * 3
    for index in range(45, 56):
        close[index] = 133 - (index - 44) * 3
    frame = pd.DataFrame({
        "trade_date": dates,
        "adjusted_close": close,
        "adjusted_open": close,
        "adjusted_high": [value * 1.01 for value in close],
        "adjusted_low": [value * 0.99 for value in close],
        "volume": 100,
        "open_interest": 200,
        "source": "test",
    })
    candidates, triggers, thresholds = scan_extreme_episodes(frame, product_code="M", horizons=(20, 60), merge_gap_sessions=10)
    assert not thresholds.empty
    assert not triggers.empty
    assert set(candidates.review_status) == {"pending"}
    assert candidates.episode_id.str.startswith("M-").all()


def test_no_event_without_enough_history():
    dates = pd.date_range("2020-01-01", periods=5, freq="D")
    frame = pd.DataFrame({"trade_date": dates, "adjusted_close": [100, 101, 102, 103, 104], "adjusted_open": [100] * 5, "adjusted_high": [101] * 5, "adjusted_low": [99] * 5, "volume": [1] * 5, "open_interest": [1] * 5, "source": ["test"] * 5})
    candidates, triggers, thresholds = scan_extreme_episodes(frame, horizons=(20, 60))
    assert candidates.empty
    assert triggers.empty
