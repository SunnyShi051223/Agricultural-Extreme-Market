# Extreme-Market Research Protocol

## Objective

Build an instrument-specific Extreme-Market research system. The research proceeds through exactly three stages: (1) Extreme-Market Database, (2) Feature & Repeatability Structure, and (3) Timing Operator. Each futures instrument is researched independently; definitions, data sources, features, and operators may differ by instrument.

## Current phase

This project currently implements Q1 for soybean meal (豆粕, DCE product code `M`) as the pilot. The remaining 28 agricultural, soft-commodity, and forest/paper products are registered for later instrument-specific work; do not imply they have been researched or downloaded.

## Research rules

- Q1 is an ex-post historical fact database and may use the full price path to identify and verify events.
- Preserve the distinction between ex-post episode labels and information that was observable on each date. Do not describe an ex-post threshold as a live signal.
- Keep raw contract observations, source provenance, contract mapping, and roll adjustments auditable. Never fabricate missing fields or silently interpolate market observations.
- Every candidate episode must have a complete path artifact and remain pending until a person reviews it. Keep the review decision, reviewer, date, and rationale.
- Later Q2/Q3 work must use only point-in-time observable features and must preserve failed experiments and negative results.
- Do not optimize a future timing operator solely on total return or Sharpe ratio. Validate over independent episodes where enough events exist.
- Use the dedicated environment `D:\Anaconda3\envs\ExtremeMarket` for project Python commands.

## Data and outputs

Raw source files are immutable snapshots. Derived data and reports must be reproducible from source data plus configuration. Document source, retrieval time, coverage, missing fields, and any transformations. No Q2 feature mining or Q3 trading logic is part of the current Q1 deliverable.
