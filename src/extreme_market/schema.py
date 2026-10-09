from __future__ import annotations

from collections.abc import Iterable

import pandas as pd


BAR_COLUMNS = [
    "trade_date",
    "contract_code",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "open_interest",
    "settlement",
    "source",
]


def normalize_bars(
    frame: pd.DataFrame,
    *,
    contract_code: str | None,
    source: str,
    cutoff_exclusive: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Normalize common domestic-futures/API column spellings without filling gaps."""
    if frame is None or frame.empty:
        return pd.DataFrame(columns=BAR_COLUMNS)

    aliases = {
        "trade_date": {"trade_date", "date", "datetime", "日期", "交易日期"},
        "open": {"open", "开盘", "开盘价"},
        "high": {"high", "最高", "最高价"},
        "low": {"low", "最低", "最低价"},
        "close": {"close", "收盘", "收盘价", "最新价"},
        "volume": {"volume", "成交量", "vol"},
        "open_interest": {"open_interest", "持仓量", "持仓", "hold", "oi"},
        "settlement": {"settlement", "结算价", "结算"},
    }
    reverse = {
        str(column).strip().lower(): canonical
        for canonical, names in aliases.items()
        for column in names
    }
    if len(frame.columns) == 0:
        return pd.DataFrame(columns=BAR_COLUMNS)
    renamed = frame.rename(columns={column: reverse.get(str(column).strip().lower(), column) for column in frame.columns}).copy()

    # Some APIs return a date index instead of a named column.
    if "trade_date" not in renamed.columns:
        renamed = renamed.reset_index()
        first = renamed.columns[0]
        renamed = renamed.rename(columns={first: "trade_date"})
    if "close" not in renamed.columns:
        raise ValueError(f"No close column in source fields: {list(frame.columns)}")
    if "trade_date" not in renamed.columns:
        raise ValueError(f"No date column in source fields: {list(frame.columns)}")

    for column in ("open", "high", "low", "volume", "open_interest", "settlement"):
        if column not in renamed.columns:
            renamed[column] = pd.NA
    renamed["trade_date"] = pd.to_datetime(renamed["trade_date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    for column in ("open", "high", "low", "close", "volume", "open_interest", "settlement"):
        renamed[column] = pd.to_numeric(renamed[column], errors="coerce")
    renamed["contract_code"] = contract_code
    renamed["source"] = source
    renamed = renamed[BAR_COLUMNS].dropna(subset=["trade_date", "close"])
    if cutoff_exclusive is not None:
        renamed = renamed.loc[renamed["trade_date"] < pd.Timestamp(cutoff_exclusive)]
    return renamed.sort_values(["trade_date", "contract_code"], kind="stable").reset_index(drop=True)


def empty_source_audit(columns: Iterable[str] = ()) -> pd.DataFrame:
    return pd.DataFrame(columns=["source", "symbol", "status", "row_count", "first_date", "last_date", "message", *columns])
