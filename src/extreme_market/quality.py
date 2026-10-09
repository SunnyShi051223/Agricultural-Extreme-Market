from __future__ import annotations

import pandas as pd


def build_gap_audit(frame: pd.DataFrame, *, minimum_calendar_gap: int = 5) -> pd.DataFrame:
    """List long date gaps and classify them without silently filling observations."""
    if frame.empty or "trade_date" not in frame:
        return pd.DataFrame(columns=["previous_trade_date", "trade_date", "gap_calendar_days", "missing_weekdays", "gap_classification"])
    dates = pd.Series(sorted(pd.to_datetime(frame.trade_date).dropna().dt.normalize().unique()))
    rows: list[dict[str, object]] = []
    for index in range(1, len(dates)):
        previous, current = pd.Timestamp(dates.iloc[index - 1]), pd.Timestamp(dates.iloc[index])
        gap_days = int((current - previous).days)
        if gap_days < minimum_calendar_gap:
            continue
        missing_weekdays = max(0, len(pd.bdate_range(previous + pd.Timedelta(days=1), current - pd.Timedelta(days=1))))
        rows.append(
            {
                "previous_trade_date": previous.date().isoformat(),
                "trade_date": current.date().isoformat(),
                "gap_calendar_days": gap_days,
                "missing_weekdays": missing_weekdays,
                "gap_classification": "likely_exchange_holiday_or_break" if missing_weekdays else "weekend_only",
            }
        )
    return pd.DataFrame(rows)


def build_price_jump_audit(series: pd.DataFrame, *, threshold: float = 0.08) -> pd.DataFrame:
    """Audit unusually large daily moves, especially important for proxy continuous series."""
    columns = [
        "previous_trade_date", "trade_date", "previous_close", "open", "close",
        "raw_close_return_1d", "adjusted_close_return_1d", "open_gap_return",
        "active_contract", "roll_adjustment_status", "jump_classification",
    ]
    if series.empty:
        return pd.DataFrame(columns=columns)
    frame = series.copy().sort_values("trade_date").reset_index(drop=True)
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.normalize()
    frame["previous_close"] = frame.close.shift(1)
    frame["previous_trade_date"] = frame.trade_date.shift(1)
    frame["open_gap_return"] = frame.open / frame.previous_close - 1
    mask = frame.adjusted_close_return_1d.abs().ge(threshold) | frame.open_gap_return.abs().ge(threshold)
    result = frame.loc[mask, [
        "previous_trade_date", "trade_date", "previous_close", "open", "close",
        "raw_close_return_1d", "adjusted_close_return_1d", "open_gap_return",
        "active_contract", "roll_adjustment_status",
    ]].copy()
    if result.empty:
        result["jump_classification"] = pd.Series(dtype="object")
        return result[columns]
    result["jump_classification"] = result.roll_adjustment_status.map(
        lambda status: "proxy_splice_review_required" if status == "no_individual_contract_mapping" else "large_move_or_roll_review_required"
    )
    return result[columns]


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
    invalid_dates = frame.loc[invalid, "trade_date"].dt.date.astype(str).tolist()
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
        "invalid_ohlc_dates": "; ".join(invalid_dates),
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
        "large_jump_rows": int(build_price_jump_audit(series).shape[0]),
    }
