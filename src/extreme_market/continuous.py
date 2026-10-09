from __future__ import annotations

import numpy as np
import pandas as pd


def _pick_dominant(day: pd.DataFrame) -> pd.Series:
    ranked = day.assign(
        _oi=day.open_interest.fillna(-np.inf),
        _volume=day.volume.fillna(-np.inf),
    ).sort_values(["_oi", "_volume", "contract_code"], ascending=[False, False, True], kind="stable")
    return ranked.iloc[0]


def build_continuous_series(
    contract_panel: pd.DataFrame,
    dominance_sessions: int = 2,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build raw and ratio-back-adjusted dominant series with an auditable roll map."""
    if contract_panel.empty:
        return pd.DataFrame(), pd.DataFrame()
    required = {"trade_date", "contract_code", "open", "high", "low", "close", "volume", "open_interest"}
    missing = required.difference(contract_panel.columns)
    if missing:
        raise ValueError(f"Contract panel missing fields: {sorted(missing)}")

    panel = contract_panel.copy()
    panel["trade_date"] = pd.to_datetime(panel.trade_date).dt.normalize()
    panel = panel.sort_values(["trade_date", "contract_code"], kind="stable")
    if panel["contract_code"].astype(str).nunique(dropna=False) == 1:
        continuous = panel.drop_duplicates(["trade_date", "contract_code"], keep="last").reset_index(drop=True).copy()
        continuous["active_contract"] = continuous["contract_code"]
        continuous["selection_reason"] = "single_source_continuous_proxy"
        continuous["roll_adjustment_factor"] = 1.0
        continuous["roll_adjustment_status"] = "no_individual_contract_mapping"
        for raw_name, adjusted_name in (("open", "adjusted_open"), ("high", "adjusted_high"), ("low", "adjusted_low"), ("close", "adjusted_close"), ("settlement", "adjusted_settlement")):
            continuous[adjusted_name] = continuous[raw_name]
        continuous["raw_close_return_1d"] = continuous.close.pct_change()
        continuous["adjusted_close_return_1d"] = continuous.adjusted_close.pct_change()
        return continuous, pd.DataFrame(columns=["trade_date", "old_contract", "new_contract", "old_close_same_day", "new_close_same_day", "ratio_adjustment_factor", "adjustment_status", "selection_reason"])
    lookup = {(row.trade_date, row.contract_code): row for row in panel.itertuples(index=False)}
    active: str | None = None
    challenger: str | None = None
    challenger_streak = 0
    # A retrospective back-adjustment is applied to the historical leg. The
    # current active contract remains at its raw level; when a roll occurs we
    # update the cumulative factor for dates before the roll.
    factor = 1.0
    chosen_rows: list[dict[str, object]] = []
    roll_rows: list[dict[str, object]] = []

    for trade_date, day in panel.groupby("trade_date", sort=True):
        best = _pick_dominant(day)
        best_code = str(best.contract_code)
        reason = "initial_dominant"
        old_code = active

        active_row = day.loc[day.contract_code.astype(str) == active] if active is not None else pd.DataFrame()
        if active is None:
            active = best_code
            challenger = None
            challenger_streak = 0
        elif active_row.empty:
            active = best_code
            challenger = None
            challenger_streak = 0
            reason = "active_contract_missing"
        elif best_code == active:
            challenger = None
            challenger_streak = 0
            reason = "dominant_unchanged"
        else:
            active_oi = active_row.iloc[0].open_interest
            best_oi = best.open_interest
            dominates = pd.notna(best_oi) and (pd.isna(active_oi) or best_oi > active_oi)
            # The best contract is evaluated against the currently active
            # contract. The first qualifying session establishes a pending
            # challenger; the second qualifying session confirms the roll on
            # that second session, so the raw series retains the old contract
            # on the first signal day.
            if dominates:
                if challenger == best_code:
                    challenger_streak += 1
                else:
                    challenger = best_code
                    challenger_streak = 1
                if challenger_streak > max(1, dominance_sessions):
                    active = best_code
                    challenger = None
                    challenger_streak = 0
                    reason = "confirmed_dominance"
                else:
                    reason = "challenger_pending"
            else:
                challenger = None
                challenger_streak = 0
                reason = "tie_or_no_oi_dominance"

        selected = day.loc[day.contract_code.astype(str) == active]
        if selected.empty:
            # Defensive fallback for data changing between ranking and selection.
            selected = day.loc[day.contract_code.astype(str) == best_code]
            active = best_code
        row = selected.iloc[0].to_dict()
        switched = old_code is not None and old_code != active
        row_factor = factor
        if switched:
            old_same_day = lookup.get((trade_date, old_code))
            new_close = float(row["close"]) if pd.notna(row["close"]) else np.nan
            old_close = float(old_same_day.close) if old_same_day is not None and pd.notna(old_same_day.close) else np.nan
            if np.isfinite(old_close) and old_close > 0 and np.isfinite(new_close) and new_close > 0:
                factor *= old_close / new_close
                row_factor = 1.0
                adjustment_status = "same_session_ratio_applied"
            else:
                adjustment_status = "missing_same_session_overlap"
            roll_rows.append(
                {
                    "trade_date": trade_date,
                    "old_contract": old_code,
                    "new_contract": active,
                    "old_close_same_day": old_close,
                    "new_close_same_day": new_close,
                    "ratio_adjustment_factor": factor,
                    "adjustment_status": adjustment_status,
                    "selection_reason": reason,
                }
            )
        else:
            adjustment_status = "no_roll"

        row.update(
            active_contract=active,
            selection_reason=reason,
            roll_adjustment_factor=row_factor,
            roll_adjustment_status=adjustment_status,
        )
        for raw_name, adjusted_name in (("open", "adjusted_open"), ("high", "adjusted_high"), ("low", "adjusted_low"), ("close", "adjusted_close"), ("settlement", "adjusted_settlement")):
            value = row.get(raw_name)
            row[adjusted_name] = float(value) * row_factor if pd.notna(value) else np.nan
        chosen_rows.append(row)

    continuous = pd.DataFrame(chosen_rows).sort_values("trade_date").reset_index(drop=True)
    # Apply the final cumulative factors to historical rows. This keeps the
    # latest contract raw while making the entire earlier path comparable.
    roll_factor_by_date: dict[pd.Timestamp, float] = {}
    if roll_rows:
        for roll in roll_rows:
            # Store the full cumulative ratio, which is equivalent to the
            # product of all individual ratios up to this roll.
            roll_factor_by_date[pd.Timestamp(roll["trade_date"])] = float(roll["ratio_adjustment_factor"])
    cumulative = 1.0
    for index, row in continuous.iterrows():
        row_date = pd.Timestamp(row["trade_date"])
        # The roll-day close is used to calculate the ratio, while the
        # historical leg before that date receives the new cumulative factor.
        row_factor = 1.0
        for date, ratio in roll_factor_by_date.items():
            if row_date < date:
                row_factor = ratio
        for raw_name, adjusted_name in (("open", "adjusted_open"), ("high", "adjusted_high"), ("low", "adjusted_low"), ("close", "adjusted_close"), ("settlement", "adjusted_settlement")):
            value = row[raw_name]
            if pd.notna(value):
                continuous.at[index, adjusted_name] = float(value) * row_factor
    rolls = pd.DataFrame(roll_rows)
    continuous["raw_close_return_1d"] = continuous.close.pct_change()
    continuous["adjusted_close_return_1d"] = continuous.adjusted_close.pct_change()
    return continuous, rolls


def build_term_structure(contract_panel: pd.DataFrame) -> pd.DataFrame:
    """Daily top-two open-interest contract spread, retained as an ex-post descriptor."""
    rows: list[dict[str, object]] = []
    for trade_date, day in contract_panel.groupby("trade_date", sort=True):
        eligible = day.dropna(subset=["open_interest", "close"]).sort_values(
            ["open_interest", "volume", "contract_code"], ascending=[False, False, True], kind="stable"
        )
        if len(eligible) < 2:
            rows.append({"trade_date": trade_date, "near_contract": None, "far_contract": None, "spread": np.nan, "spread_pct": np.nan, "source": "AkShare/Sina"})
            continue
        near, far = eligible.iloc[0], eligible.iloc[1]
        spread = float(far.close - near.close)
        rows.append(
            {
                "trade_date": trade_date,
                "near_contract": near.contract_code,
                "far_contract": far.contract_code,
                "near_close": near.close,
                "far_close": far.close,
                "spread": spread,
                "spread_pct": spread / float(near.close) if float(near.close) else np.nan,
                "source": "AkShare/Sina",
                "availability_note": "Same-day end-of-session ranking; ex-post Q1 descriptor",
            }
        )
    return pd.DataFrame(rows)
