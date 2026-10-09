from __future__ import annotations

import time
from datetime import date

import pandas as pd

from extreme_market.schema import BAR_COLUMNS, normalize_bars


def contract_codes(product_code: str, start: str, cutoff_exclusive: str) -> list[str]:
    start_date = pd.Timestamp(start).date()
    cutoff = pd.Timestamp(cutoff_exclusive).date()
    result: list[str] = []
    year, month = start_date.year, start_date.month
    while date(year, month, 1) < cutoff:
        result.append(f"{product_code}{year % 100:02d}{month:02d}")
        month += 1
        if month == 13:
            month = 1
            year += 1
    return result


def fetch_contract_panel(
    product_code: str,
    start: str,
    cutoff_exclusive: str,
    pause_seconds: float = 0.15,
    progress=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch individual DCE contract histories from Sina through AkShare."""
    import akshare as ak

    # Sina exposes a long-history dominant-contract proxy (`M0`) in one
    # request. It is the reliable baseline for a first Q1 build and avoids
    # hundreds of empty delivery-month requests. The audit explicitly labels
    # this as a continuous proxy; individual delivery bars can be added later
    # without changing the derived schema.
    proxy_audit = {
        "source": "AkShare/Sina",
        "symbol": f"{product_code}0",
        "status": "failed",
        "row_count": 0,
        "first_date": "",
        "last_date": "",
        "message": "",
    }
    try:
        raw_proxy = ak.futures_zh_daily_sina(symbol=f"{product_code}0")
        proxy = normalize_bars(raw_proxy, contract_code=f"{product_code}0", source="AkShare/Sina continuous proxy", cutoff_exclusive=cutoff_exclusive)
        proxy = proxy.loc[proxy.trade_date >= pd.Timestamp(start)].reset_index(drop=True)
        if not proxy.empty:
            proxy_audit.update(status="success_continuous_proxy", row_count=len(proxy), first_date=str(proxy.trade_date.min().date()), last_date=str(proxy.trade_date.max().date()), message="Long-history dominant-contract proxy; individual delivery-month panel not requested in this fast path")
            return proxy, pd.DataFrame([proxy_audit])
        proxy_audit["message"] = "Proxy returned no observations before cutoff"
    except Exception as exc:
        proxy_audit["message"] = f"{type(exc).__name__}: {exc}"

    codes = contract_codes(product_code, start, cutoff_exclusive)
    panels: list[pd.DataFrame] = []
    audits: list[dict[str, object]] = []
    for index, code in enumerate(codes, start=1):
        row: dict[str, object] = {
            "source": "AkShare/Sina",
            "symbol": code,
            "status": "failed",
            "row_count": 0,
            "first_date": "",
            "last_date": "",
            "message": "",
        }
        try:
            raw = ak.futures_zh_daily_sina(symbol=code)
            if raw is None or getattr(raw, "empty", True) or len(getattr(raw, "columns", [])) == 0:
                row.update(status="no_data", message="Provider returned an empty response")
                audits.append(row)
                if progress:
                    progress(index, len(codes), code, str(row["status"]))
                if pause_seconds > 0 and index < len(codes):
                    time.sleep(pause_seconds)
                continue
            normalized = normalize_bars(raw, contract_code=code, source="AkShare/Sina", cutoff_exclusive=cutoff_exclusive)
            normalized = normalized.loc[normalized.trade_date >= pd.Timestamp(start)]
            if normalized.empty:
                row.update(status="no_data", message="No observations for this delivery month")
            else:
                row.update(
                    status="success",
                    row_count=len(normalized),
                    first_date=str(normalized.trade_date.min().date()),
                    last_date=str(normalized.trade_date.max().date()),
                )
                panels.append(normalized)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            # Sina's endpoint raises a pandas reshape error for delivery
            # months that have never traded. Treat that response as a normal
            # no-data month, while retaining all other failures in the audit.
            if isinstance(exc, ValueError) and "Length mismatch" in str(exc):
                row["status"] = "no_data"
                row["message"] = "Provider returned no rows for this delivery month"
            else:
                row["message"] = message
        audits.append(row)
        if progress:
            progress(index, len(codes), code, str(row["status"]))
        if pause_seconds > 0 and index < len(codes):
            time.sleep(pause_seconds)

    panel = pd.concat(panels, ignore_index=True) if panels else pd.DataFrame(columns=BAR_COLUMNS)
    if not panel.empty:
        panel = panel.drop_duplicates(["trade_date", "contract_code"], keep="last")
        panel = panel.sort_values(["trade_date", "contract_code"], kind="stable").reset_index(drop=True)
    return panel, pd.concat([pd.DataFrame([proxy_audit]), pd.DataFrame(audits)], ignore_index=True, sort=False)
