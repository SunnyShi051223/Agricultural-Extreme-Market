from __future__ import annotations

import pandas as pd


def inspect_contract_panel(panel: pd.DataFrame) -> dict[str, object]:
    if panel.empty:
        return {
            "status": "no_contract_data",
            "rows": 0,
            "contracts": 0,
            "first_date": "",
            "last_date": "",
            "duplicate_contract_dates": 0,
            "invalid_ohlc_rows": 0,
            "negative_volume_rows": 0,
            "negative_open_interest_rows": 0,
            "missing_volume_rows": 0,
            "missing_open_interest_rows": 0,
            "gaps_over_four_calendar_days": "",
        }
    frame = panel.copy()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    duplicated = int(frame.duplicated(["trade_date", "contract_code"]).sum())
    invalid = (
        (frame.low > frame.high)
        | (frame.open < frame.low)
        | (frame.open > frame.high)
        | (frame.close < frame.low)
        | (frame.close > frame.high)
    ).fillna(False)
    date_series = pd.Series(sorted(frame.trade_date.dropna().unique()))
    diffs = date_series.diff().dt.days
    gaps = [
        f"{date_series.iloc[i-1].date()}..{date_series.iloc[i].date()} ({int(diffs.iloc[i])}d)"
        for i in range(1, len(date_series))
        if pd.notna(diffs.iloc[i]) and int(diffs.iloc[i]) > 4
    ]
    return {
        "status": "ok" if duplicated == 0 and int(invalid.sum()) == 0 else "review_required",
        "rows": len(frame),
        "contracts": int(frame.contract_code.nunique()),
        "first_date": str(frame.trade_date.min().date()),
        "last_date": str(frame.trade_date.max().date()),
        "duplicate_contract_dates": duplicated,
        "invalid_ohlc_rows": int(invalid.sum()),
        "negative_volume_rows": int((frame.volume < 0).fillna(False).sum()),
        "negative_open_interest_rows": int((frame.open_interest < 0).fillna(False).sum()),
        "missing_volume_rows": int(frame.volume.isna().sum()),
        "missing_open_interest_rows": int(frame.open_interest.isna().sum()),
        "gaps_over_four_calendar_days": "; ".join(gaps),
    }


def inspect_continuous(series: pd.DataFrame, rolls: pd.DataFrame) -> dict[str, object]:
    if series.empty:
        return {"continuous_status": "no_continuous_data", "continuous_rows": 0, "roll_count": 0, "rolls_without_ratio_adjustment": 0}
    dates = pd.to_datetime(series.trade_date)
    return {
        "continuous_status": "ok" if not dates.duplicated().any() and dates.is_monotonic_increasing else "review_required",
        "continuous_rows": len(series),
        "continuous_first_date": str(dates.min().date()),
        "continuous_last_date": str(dates.max().date()),
        "roll_count": len(rolls),
        "rolls_without_ratio_adjustment": int((rolls.adjustment_status != "same_session_ratio_applied").sum()) if not rolls.empty else 0,
        "missing_open_interest_continuous_rows": int(series.open_interest.isna().sum()) if "open_interest" in series else len(series),
        "max_abs_raw_1d_return": float(series.raw_close_return_1d.abs().max()) if "raw_close_return_1d" in series else float("nan"),
        "max_abs_adjusted_1d_return": float(series.adjusted_close_return_1d.abs().max()) if "adjusted_close_return_1d" in series else float("nan"),
    }
