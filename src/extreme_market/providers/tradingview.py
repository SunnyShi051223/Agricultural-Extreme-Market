from __future__ import annotations

import os

import pandas as pd

from extreme_market.schema import normalize_bars


def fetch_continuous(
    symbol: str,
    exchange: str,
    bars: int,
    cutoff_exclusive: str,
) -> tuple[pd.DataFrame, dict[str, object]]:
    """Try TradingView's public chart feed through tvDatafeed; never fabricate output."""
    audit: dict[str, object] = {
        "source": "TradingView",
        "symbol": f"{exchange}:{symbol}",
        "status": "failed",
        "row_count": 0,
        "first_date": "",
        "last_date": "",
        "message": "",
    }
    try:
        try:
            from tvDatafeed import Interval, TvDatafeed
        except ModuleNotFoundError as exc:
            raise RuntimeError("tvDatafeed is not available in the dedicated environment; TradingView attempt recorded as unavailable") from exc

        username = os.getenv("TV_USERNAME")
        password = os.getenv("TV_PASSWORD")
        client = TvDatafeed(username=username, password=password) if username and password else TvDatafeed()
        result = client.get_hist(
            symbol=symbol,
            exchange=exchange,
            interval=Interval.in_daily,
            n_bars=bars,
        )
        if result is None or result.empty:
            raise RuntimeError("TradingView returned no daily bars for the configured symbol")
        normalized = normalize_bars(result, contract_code=None, source="TradingView", cutoff_exclusive=cutoff_exclusive)
        audit.update(
            status="success" if not normalized.empty else "empty_after_cutoff",
            row_count=len(normalized),
            first_date=str(normalized.trade_date.min().date()) if not normalized.empty else "",
            last_date=str(normalized.trade_date.max().date()) if not normalized.empty else "",
        )
        if normalized.empty:
            audit["message"] = "No bars before the exclusive cutoff"
        return normalized, audit
    except Exception as exc:  # source availability and symbol support vary by account/region
        audit["message"] = f"{type(exc).__name__}: {exc}"
        return pd.DataFrame(), audit
