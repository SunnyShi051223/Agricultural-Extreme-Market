from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TailThreshold:
    horizon: int
    lower: float
    upper: float
    observations: int


def _build_triggers(
    series: pd.DataFrame,
    horizons: tuple[int, ...],
    lower_quantile: float,
    upper_quantile: float,
) -> tuple[pd.DataFrame, list[TailThreshold]]:
    triggers: list[dict[str, object]] = []
    thresholds: list[TailThreshold] = []
    for horizon in horizons:
        col = f"return_{horizon}d"
        values = series[col].dropna()
        if values.empty:
            continue
        lower = float(values.quantile(lower_quantile))
        upper = float(values.quantile(upper_quantile))
        thresholds.append(TailThreshold(horizon, lower, upper, int(values.size)))
        for position, value in enumerate(series[col].to_numpy()):
            if not np.isfinite(value):
                continue
            if value >= upper:
                direction = "Extreme-Up"
            elif value <= lower:
                direction = "Extreme-Down"
            else:
                continue
            start_position = max(0, position - horizon)
            triggers.append(
                {
                    "direction": direction,
                    "horizon": horizon,
                    "start_position": start_position,
                    "signal_position": position,
                    "return_at_trigger": float(value),
                    "lower_threshold": lower,
                    "upper_threshold": upper,
                }
            )
    return pd.DataFrame(triggers), thresholds


def _merge_same_direction(triggers: pd.DataFrame, gap_sessions: int) -> list[dict[str, object]]:
    """Merge same-side trigger windows that overlap or are at most N sessions apart."""
    merged: list[dict[str, object]] = []
    if triggers.empty:
        return merged
    for direction, side in triggers.groupby("direction", sort=True):
        side = side.sort_values(["start_position", "signal_position", "horizon"], kind="stable")
        current: dict[str, object] | None = None
        for trigger in side.to_dict("records"):
            start = int(trigger["start_position"])
            end = int(trigger["signal_position"])
            if current is None:
                current = {
                    "direction": direction,
                    "start_position": start,
                    "last_signal_position": end,
                    "coverage_end_position": end,
                    "triggers": [trigger],
                }
                continue
            coverage_end = int(current["coverage_end_position"])
            missing_sessions = max(0, start - coverage_end - 1)
            if start <= coverage_end or missing_sessions <= gap_sessions:
                current["start_position"] = min(int(current["start_position"]), start)
                current["last_signal_position"] = max(int(current["last_signal_position"]), end)
                current["coverage_end_position"] = max(coverage_end, end)
                current["triggers"].append(trigger)
            else:
                merged.append(current)
                current = {
                    "direction": direction,
                    "start_position": start,
                    "last_signal_position": end,
                    "coverage_end_position": end,
                    "triggers": [trigger],
                }
        if current is not None:
            merged.append(current)
    return sorted(merged, key=lambda item: (int(item["start_position"]), str(item["direction"])))


def scan_extreme_episodes(
    continuous: pd.DataFrame,
    *,
    product_code: str = "M",
    horizons: tuple[int, ...] = (20, 60),
    lower_quantile: float = 0.025,
    upper_quantile: float = 0.975,
    merge_gap_sessions: int = 10,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Create ex-post event candidates from full-history adjusted close return tails."""
    if continuous.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    series = continuous.copy().sort_values("trade_date").reset_index(drop=True)
    if "adjusted_close" not in series:
        raise ValueError("continuous series must contain adjusted_close")
    series["trade_date"] = pd.to_datetime(series.trade_date).dt.normalize()
    for horizon in horizons:
        series[f"return_{horizon}d"] = series.adjusted_close.pct_change(horizon)

    triggers, thresholds = _build_triggers(series, horizons, lower_quantile, upper_quantile)
    merged = _merge_same_direction(triggers, merge_gap_sessions)
    candidates: list[dict[str, object]] = []
    path_records: list[dict[str, object]] = []

    for direction in ("Extreme-Up", "Extreme-Down"):
        side_episodes = [item for item in merged if item["direction"] == direction]
        side_episodes.sort(key=lambda item: int(item["start_position"]))
        for side_number, item in enumerate(side_episodes, start=1):
            start_pos = int(item["start_position"])
            signal_pos = [int(row["signal_position"]) for row in item["triggers"]]
            accel_pos = min(signal_pos)
            end_pos = max(signal_pos)
            segment = series.iloc[start_pos : end_pos + 1]
            if segment.empty:
                continue
            if direction == "Extreme-Up":
                extreme_relative = segment.adjusted_high.astype(float).idxmax()
                extreme_label = "highest_point"
            else:
                extreme_relative = segment.adjusted_low.astype(float).idxmin()
                extreme_label = "lowest_point"
            extreme_pos = int(extreme_relative)
            start_close = float(series.iloc[start_pos].adjusted_close)
            end_close = float(series.iloc[end_pos].adjusted_close)
            trigger_rows = item["triggers"]
            accel_rows = [row for row in trigger_rows if int(row["signal_position"]) == accel_pos]
            accel_trigger = sorted(accel_rows, key=lambda row: int(row["horizon"]))[0]
            event_id = f"{product_code}-{ 'UP' if direction == 'Extreme-Up' else 'DOWN'}-{side_number:04d}"
            returns_at_accel = {
                f"acceleration_return_{h}d": (
                    float(series.iloc[accel_pos].adjusted_close / series.iloc[accel_pos - h].adjusted_close - 1)
                    if accel_pos >= h and pd.notna(series.iloc[accel_pos - h].adjusted_close)
                    else np.nan
                )
                for h in (1, 5, 20, 60)
            }
            daily_returns = segment.adjusted_close.astype(float).pct_change().dropna()
            volatility = float(daily_returns.std(ddof=1) * np.sqrt(252)) if len(daily_returns) > 1 else np.nan
            start_level = float(series.iloc[start_pos].adjusted_close)
            high_level = float(segment.adjusted_high.max())
            low_level = float(segment.adjusted_low.min())
            same_direction = "UP" if direction == "Extreme-Up" else "DOWN"
            candidates.append(
                {
                    "instrument": "豆粕",
                    "product_code": product_code,
                    "episode_id": event_id,
                    "direction": direction,
                    "event_start_date": series.iloc[start_pos].trade_date.date().isoformat(),
                    "acceleration_date": series.iloc[accel_pos].trade_date.date().isoformat(),
                    "acceleration_horizon_days": int(accel_trigger["horizon"]),
                    "extreme_point_type": extreme_label,
                    "extreme_point_date": series.iloc[extreme_pos].trade_date.date().isoformat(),
                    "event_end_date": series.iloc[end_pos].trade_date.date().isoformat(),
                    "start_close_adjusted": start_close,
                    "end_close_adjusted": end_close,
                    "event_cumulative_return": end_close / start_close - 1 if start_close else np.nan,
                    "max_up_from_start": high_level / start_level - 1 if start_level else np.nan,
                    "max_down_from_start": low_level / start_level - 1 if start_level else np.nan,
                    "annualized_realized_volatility": volatility,
                    "mean_volume": float(segment.volume.mean()) if "volume" in segment else np.nan,
                    "total_volume": float(segment.volume.sum(min_count=1)) if "volume" in segment else np.nan,
                    "mean_open_interest": float(segment.open_interest.mean()) if "open_interest" in segment else np.nan,
                    "max_open_interest": float(segment.open_interest.max()) if "open_interest" in segment else np.nan,
                    "trigger_count": len(trigger_rows),
                    "trigger_horizons": ";".join(map(str, sorted({int(row["horizon"]) for row in trigger_rows}))),
                    "tail_thresholds": ";".join(
                        f"{h}:{next((f'{t.lower:.8f}/{t.upper:.8f}' for t in thresholds if t.horizon == h), 'NA')}"
                        for h in sorted({int(row["horizon"]) for row in trigger_rows})
                    ),
                    "source": ";".join(sorted(set(segment.source.dropna().astype(str)))) if "source" in segment else "",
                    **returns_at_accel,
                    "review_status": "pending",
                    "review_decision": "",
                    "reviewer": "",
                    "review_date": "",
                    "review_notes": "",
                    "chart_path": f"episode_charts/{event_id}.png",
                    "path_csv": f"episode_paths/{event_id}.csv",
                }
            )
            for row in trigger_rows:
                path_records.append({"episode_id": event_id, **row})

    candidates_frame = pd.DataFrame(candidates).sort_values(["event_start_date", "episode_id"]).reset_index(drop=True) if candidates else pd.DataFrame()
    if not candidates_frame.empty:
        candidates_frame["overlaps_opposite_direction"] = False
        for i, left in candidates_frame.iterrows():
            for j in range(i + 1, len(candidates_frame)):
                right = candidates_frame.iloc[j]
                if left.direction == right.direction:
                    continue
                overlap = (left.event_start_date <= right.event_end_date) and (right.event_start_date <= left.event_end_date)
                if overlap:
                    candidates_frame.loc[[i, j], "overlaps_opposite_direction"] = True

    thresholds_frame = pd.DataFrame([threshold.__dict__ for threshold in thresholds])
    return candidates_frame, pd.DataFrame(path_records), thresholds_frame
