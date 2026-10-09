# Agricultural Extreme Market

Q1 pilot database for Dalian Commodity Exchange soybean meal futures.

## Environment

Create or reproduce the dedicated environment from the Anaconda installation:

```powershell
D:\Anaconda3\Scripts\conda.exe env create --prefix D:\Anaconda3\envs\ExtremeMarket --file environment.yml
```

Project Python commands should use:

```powershell
D:\Anaconda3\envs\ExtremeMarket\python.exe -m extreme_market.cli --help
```

## Project layout

- `data/market/raw/`: source snapshots and retrieval audit.
- `data/market/processed/`: normalized contract panel and continuous series.
- `data/fundamental/`: point-in-time external-data template and source inventory.
- `instruments/豆粕/`: soybean meal settings and Q1 outputs.
- `reports/`: coverage, data-quality, and review summaries.
- `src/extreme_market/`: download, normalization, roll, episode, chart, and validation code.
- `tests/`: tests for roll adjustment, event thresholds, event merging, and output integrity.

## Q1 workflow

1. Attempt TradingView retrieval for the configured continuous symbol and retain its response or failure in the source audit.
2. Retrieve the long-history public Sina `M0` dominant-contract proxy through AkShare as the reliable fallback, preserving OHLCV and open interest. The source audit labels this as a continuous proxy; individual delivery-month bars are a separately extensible acquisition step.
3. When an individual contract panel is available, select the active contract using open interest, volume as the tie-breaker, and two consecutive sessions of dominance before a roll. The current pilot uses `M0`, so no roll is inferred from unavailable delivery-month observations.
4. Keep both raw dominant-proxy prices and a ratio-back-adjusted retrospective series. Missing same-session roll overlap is flagged rather than hidden.
5. Scan the complete adjusted close history for instrument-specific 20/60-session return tails (2.5% on each side), merge same-direction windows, and write pending candidates plus charts for human review.

The cutoff is exclusive: dates on or after 2026-10-08 are excluded. The pipeline uses the latest source data before that cutoff and reports the actual latest observed trading date.

## Commands

```powershell
# Download sources, build contract panel/continuous series, and scan candidates
D:\Anaconda3\envs\ExtremeMarket\python.exe -m extreme_market.cli build --config instruments\豆粕\config.yaml

# Rebuild derived products from saved raw files, without network access
D:\Anaconda3\envs\ExtremeMarket\python.exe -m extreme_market.cli rebuild --config instruments\豆粕\config.yaml

# Run validation tests
D:\Anaconda3\envs\ExtremeMarket\python.exe -m pytest
```

Raw source data are not committed to Git. Each download creates a source audit and the report states actual coverage and any unavailable fields.
