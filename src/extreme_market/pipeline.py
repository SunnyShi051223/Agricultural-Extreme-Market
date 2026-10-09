from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from extreme_market.charts import draw_episode_chart
from extreme_market.continuous import build_continuous_series, build_term_structure
from extreme_market.episodes import scan_extreme_episodes
from extreme_market.providers.akshare_sina import fetch_contract_panel
from extreme_market.providers.tradingview import fetch_continuous
from extreme_market.quality import build_gap_audit, build_price_jump_audit, inspect_continuous, inspect_contract_panel
from extreme_market.schema import BAR_COLUMNS


def _resolve(base: Path, configured: str) -> Path:
    return (base / configured).resolve()


def load_config(config_path: str | Path) -> tuple[dict, Path]:
    path = Path(config_path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle), path.parent.parent.parent


def _write_frame(frame: pd.DataFrame, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() == ".parquet":
        frame.to_parquet(target, index=False)
    else:
        frame.to_csv(target, index=False, encoding="utf-8-sig")


def _manifest(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_external_inventory(target: Path, term_available: bool, instrument_name: str = "instrument") -> None:
    rows = [
        ("term_structure", "Available from individual contract bars; top-two open-interest spread; same-day ex-post ranking" if term_available else "not_available_from_continuous_proxy", "AkShare/Sina futures contracts"),
        ("spot_basis", "not_yet_acquired", "No verified point-in-time source configured"),
        (f"{instrument_name}_inventory", "not_yet_acquired", "Inventory source requires separate source validation"),
        ("crush_margin_and_processing_profit", "not_yet_acquired", "No verified point-in-time source configured"),
        ("supply_demand_and_imports", "not_yet_acquired", "No verified point-in-time source configured"),
        ("weather_and_crop_conditions", "not_yet_acquired", "No verified point-in-time source configured"),
        ("macro_variables", "not_yet_acquired", "No instrument-specific macro series configured in Q1 pilot"),
    ]
    pd.DataFrame(rows, columns=["variable_group", "status", "source_or_note"]).to_csv(target, index=False, encoding="utf-8-sig")


def build_from_sources(config: dict, base_dir: Path, progress=print) -> dict[str, object]:
    instrument = config["instrument"]
    episode_cfg = config["episodes"]
    continuous_cfg = config["continuous"]
    paths = config["paths"]
    raw_dir = _resolve(base_dir, paths["raw_dir"])
    processed_dir = _resolve(base_dir, paths["processed_dir"])
    instrument_dir = _resolve(base_dir, paths["instrument_dir"])
    reports_dir = _resolve(base_dir, paths["reports_dir"])
    for directory in (raw_dir, processed_dir, instrument_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    tv_bars, tv_audit = fetch_continuous(
        instrument["tradingview_symbol"],
        instrument["tradingview_exchange"],
        int(instrument["tradingview_bars"]),
        instrument["cutoff_exclusive"],
    )
    if not tv_bars.empty:
        tv_bars.to_csv(raw_dir / "tradingview_continuous_daily.csv", index=False, encoding="utf-8-sig")
        progress(f"TradingView: {len(tv_bars)} daily bars ({tv_audit['first_date']} to {tv_audit['last_date']})")
    else:
        progress(f"TradingView unavailable: {tv_audit['message']}")

    def on_contract(index: int, total: int, code: str, status: str) -> None:
        if index == total or index % 24 == 0:
            progress(f"AkShare/Sina contract scan: {index}/{total}; latest {code}: {status}")

    contract_panel, contract_audit = fetch_contract_panel(
        instrument["product_code"],
        instrument["contract_search_start"],
        instrument["cutoff_exclusive"],
        float(instrument.get("request_pause_seconds", 0.15)),
        on_contract,
    )
    if not contract_panel.empty:
        contract_panel.to_parquet(raw_dir / "akshare_sina_contract_panel.parquet", index=False)
    else:
        # TradingView can still support a price-only pilot, but it cannot stand in for contract-level history.
        contract_panel = tv_bars.copy()
        if not contract_panel.empty:
            contract_panel["contract_code"] = f"{instrument['product_code']}-TV-CONTINUOUS"
            contract_panel["source"] = "TradingView"
            contract_panel["open_interest"] = pd.NA
            contract_panel.to_parquet(raw_dir / "tradingview_price_only_contract_panel.parquet", index=False)

    audit_frame = pd.concat([pd.DataFrame([tv_audit]), contract_audit], ignore_index=True, sort=False)
    audit_frame.to_csv(reports_dir / "data_source_attempts.csv", index=False, encoding="utf-8-sig")
    if contract_panel.empty:
        _write_unavailable_outputs(instrument_dir, reports_dir, audit_frame, instrument["cutoff_exclusive"])
        return {"status": "no_market_data", "source_audit": str(reports_dir / "data_source_attempts.csv")}

    continuous, rolls = build_continuous_series(contract_panel, int(continuous_cfg["dominance_sessions"]))
    continuous.to_parquet(processed_dir / "continuous_main_raw_and_adjusted.parquet", index=False)
    rolls.to_csv(processed_dir / "roll_adjustments.csv", index=False, encoding="utf-8-sig")
    term = build_term_structure(contract_panel)
    term.to_csv(processed_dir / "term_structure_top_open_interest.csv", index=False, encoding="utf-8-sig")
    build_gap_audit(contract_panel).to_csv(reports_dir / "trading_date_gap_audit.csv", index=False, encoding="utf-8-sig")
    build_price_jump_audit(continuous).to_csv(reports_dir / "price_jump_audit.csv", index=False, encoding="utf-8-sig")

    if not tv_bars.empty:
        tv_compare = tv_bars[["trade_date", "close"]].rename(columns={"close": "tradingview_close"}).merge(
            continuous[["trade_date", "close", "adjusted_close", "active_contract"]].rename(columns={"close": "sina_main_raw_close"}),
            on="trade_date",
            how="inner",
        )
        if not tv_compare.empty:
            tv_compare["raw_price_difference"] = tv_compare.sina_main_raw_close - tv_compare.tradingview_close
            tv_compare["raw_price_difference_pct"] = tv_compare.raw_price_difference / tv_compare.tradingview_close
            tv_compare.to_csv(processed_dir / "tradingview_sina_price_comparison.csv", index=False, encoding="utf-8-sig")

    candidates, trigger_map, thresholds = scan_extreme_episodes(
        continuous,
        instrument_name=instrument["name_zh"],
        product_code=instrument["product_code"],
        horizons=tuple(int(value) for value in episode_cfg["horizons"]),
        lower_quantile=float(episode_cfg["lower_quantile"]),
        upper_quantile=float(episode_cfg["upper_quantile"]),
        merge_gap_sessions=int(episode_cfg["merge_gap_sessions"]),
    )
    q1_dir = instrument_dir / "01_Extreme_Market_Database"
    charts_dir = q1_dir / "episode_charts"
    paths_dir = q1_dir / "episode_paths"
    charts_dir.mkdir(parents=True, exist_ok=True)
    paths_dir.mkdir(parents=True, exist_ok=True)
    candidate_file = q1_dir / "extreme_episodes_candidates.csv"
    candidates.to_csv(candidate_file, index=False, encoding="utf-8-sig")
    trigger_map.to_csv(q1_dir / "episode_trigger_windows.csv", index=False, encoding="utf-8-sig")
    thresholds.to_csv(q1_dir / "tail_thresholds.csv", index=False, encoding="utf-8-sig")
    review_cols = ["episode_id", "review_status", "review_decision", "reviewer", "review_date", "review_notes"]
    candidates[review_cols].to_csv(q1_dir / "candidate_review_log.csv", index=False, encoding="utf-8-sig")

    for _, episode in candidates.iterrows():
        draw_episode_chart(continuous, episode, q1_dir / episode.chart_path, int(episode_cfg["chart_context_sessions"]))
        start = pd.Timestamp(episode.event_start_date)
        end = pd.Timestamp(episode.event_end_date)
        dates = pd.to_datetime(continuous.trade_date)
        start_pos = max(0, int(dates.searchsorted(start)) - int(episode_cfg["chart_context_sessions"]))
        end_pos = min(len(continuous), int(dates.searchsorted(end, side="right")) + int(episode_cfg["chart_context_sessions"]))
        path = continuous.iloc[start_pos:end_pos].copy()
        path["episode_id"] = episode.episode_id
        path["in_candidate_interval"] = path.trade_date.between(start, end)
        path.to_csv(q1_dir / episode.path_csv, index=False, encoding="utf-8-sig")

    quality = inspect_contract_panel(contract_panel)
    quality.update(inspect_continuous(continuous, rolls))
    quality.update(
        {
            "instrument": instrument["name_zh"],
            "cutoff_exclusive": instrument["cutoff_exclusive"],
            "tradingview_status": tv_audit["status"],
            "tradingview_rows": tv_audit["row_count"],
            "candidate_episode_count": len(candidates),
            "pending_review_count": int((candidates.review_status == "pending").sum()) if "review_status" in candidates else 0,
            "term_structure_rows": len(term),
        }
    )
    pd.DataFrame([quality]).to_csv(reports_dir / "data_quality_summary.csv", index=False, encoding="utf-8-sig")
    _write_external_inventory(reports_dir / "external_data_inventory.csv", bool("far_contract" in term and term["far_contract"].notna().any()), instrument["name_zh"])
    _write_coverage_report(reports_dir / "q1_coverage_report.md", quality, audit_frame, thresholds, candidates)
    _manifest(
        reports_dir / "build_manifest.json",
        {
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "instrument": instrument,
            "cutoff_exclusive": instrument["cutoff_exclusive"],
            "rows_contract_panel": len(contract_panel),
            "rows_continuous": len(continuous),
            "candidate_episodes": len(candidates),
            "quality_outputs": ["trading_date_gap_audit.csv", "price_jump_audit.csv"],
            "event_definition": "Full-history empirical 2.5%/97.5% tails for 20/60-session adjusted-close returns; same-direction windows are merged by overlap or <=10 trading-session gaps; labels are ex-post and pending manual review.",
        },
    )
    return {
        "status": "built",
        "contract_rows": len(contract_panel),
        "continuous_rows": len(continuous),
        "candidates": len(candidates),
        "source_audit": str(reports_dir / "data_source_attempts.csv"),
        "candidate_file": str(candidate_file),
        "report": str(reports_dir / "q1_coverage_report.md"),
    }


def _write_unavailable_outputs(instrument_dir: Path, reports_dir: Path, audits: pd.DataFrame, cutoff: str) -> None:
    q1_dir = instrument_dir / "01_Extreme_Market_Database"
    q1_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(columns=["episode_id", "direction", "event_start_date", "acceleration_date", "extreme_point_date", "event_end_date", "review_status"]).to_csv(
        q1_dir / "extreme_episodes_candidates.csv", index=False, encoding="utf-8-sig"
    )
    (reports_dir / "q1_coverage_report.md").write_text(
        "# 豆粕 Q1 数据覆盖报告\n\n"
        f"- 排他截止日期：{cutoff}\n"
        "- 结果：没有可用行情源返回可处理的日线数据，因此未生成事件标签或图表。\n"
        "- 请检查 `data_source_attempts.csv` 中 TradingView 符号、网络或来源接口的失败信息。\n"
        "- 未生成或填充任何合成行情。\n",
        encoding="utf-8",
    )
    audits.to_csv(reports_dir / "data_source_attempts.csv", index=False, encoding="utf-8-sig")


def _write_coverage_report(target: Path, quality: dict[str, object], audits: pd.DataFrame, thresholds: pd.DataFrame, candidates: pd.DataFrame) -> None:
    audit_columns = [col for col in ("source", "symbol", "status", "row_count", "first_date", "last_date", "message") if col in audits.columns]
    audit_table = audits[audit_columns] if audit_columns else pd.DataFrame(columns=["source", "symbol", "status", "row_count", "first_date", "last_date", "message"])
    threshold_table = thresholds.to_markdown(index=False) if not thresholds.empty else "No thresholds could be estimated."
    if {"source", "status"}.issubset(audits.columns):
        source_summary = audits.groupby(["source", "status"], dropna=False).size().rename("attempts").reset_index().to_markdown(index=False)
    else:
        source_summary = "No new source retrieval was performed during rebuild; source audit is retained from the original build."
    text = [
        f"# {quality.get('instrument', 'Instrument')} Q1 Extreme-Market 数据覆盖与质量报告",
        "",
        "本报告只记录历史数据和事后事件候选，不构成实时信号或交易结论。",
        "",
        "## 覆盖与质量",
        "",
        f"- 行情状态：{quality.get('status')}; {quality.get('rows', 0)} 条合约日线、{quality.get('contracts', 0)} 个合约。",
        f"- 合约面板覆盖：{quality.get('first_date', '')} 至 {quality.get('last_date', '')}；连续序列覆盖：{quality.get('continuous_first_date', '')} 至 {quality.get('continuous_last_date', '')}。",
        f"- 缺失成交量：{quality.get('missing_volume_rows', 0)} 行；缺失持仓量：{quality.get('missing_open_interest_rows', 0)} 行。",
        f"- 重复合约交易日：{quality.get('duplicate_contract_dates', 0)}；OHLC关系异常：{quality.get('invalid_ohlc_rows', 0)} 行（日期：{quality.get('invalid_ohlc_dates', '') or '无'}）。",
        f"- 换月：{quality.get('roll_count', 0)} 次；缺少同日新旧合约收盘价、未能比例调整：{quality.get('rolls_without_ratio_adjustment', 0)} 次。",
        f"- 连续主力原始/调整后最大单日绝对收益：{quality.get('max_abs_raw_1d_return', float('nan'))} / {quality.get('max_abs_adjusted_1d_return', float('nan'))}；超过8%的跳变：{quality.get('large_jump_rows', 0)} 行，详见 `price_jump_audit.csv`。",
        f"- 候选事件：{quality.get('candidate_episode_count', 0)} 条；当前待人工审核：{quality.get('pending_review_count', 0)} 条。",
        f"- 超过4个自然日的数据间隔（需结合中国交易所节假日核验）：{quality.get('gaps_over_four_calendar_days', '') or '无'}。",
        "",
        "## 来源状态",
        "",
        source_summary,
        "",
        "|来源|代码|状态|行数|最早|最晚|说明|",
        "|---|---|---:|---:|---|---|---|",
    ]
    for _, row in audit_table.iterrows():
        vals = [str(row.get(key, "")).replace("|", "\\|").replace("\n", " ") for key in ("source", "symbol", "status", "row_count", "first_date", "last_date", "message")]
        text.append("|" + "|".join(vals) + "|")
    text.extend(["", "## 20/60日收益尾部阈值", "", threshold_table, "", "## 外部字段", "", "本次行情源成功返回的是 AkShare/Sina 的长历史品种连续代理，因此期限结构、基差、库存、产业利润、供需、天气与宏观字段没有被冒充为已获得；它们以缺失/待采集状态登记，不以零值代替。若后续取得逐合约面板，程序可重新构造逐日 top-two 持仓量期限结构。", "", "## 数据缺口与价格跳变审计", "", "`trading_date_gap_audit.csv` 列出较长日期间隔并区分可能的交易所节假日/休市与其他缺口；`price_jump_audit.csv` 列出超过8%的日收益或开盘跳空。对于连续代理，标记为 `proxy_splice_review_required` 的跳变不能解释为真实逐合约收益，后续需以交割合约面板回溯核实。", "", "## 候选定义与审核", "", "使用比例回溯调整收盘价计算全历史20/60交易日累计收益；每个周期分别取下尾2.5%和上尾2.5%。窗口重叠或同方向间隔不超过10个交易日时合并。事件区间的结束规则为合并窗口中的最后一个尾部触发日；事件表额外记录持续交易日数、加速前/极值/结束阶段收益、极值后反转和事件后5/20/60日收益。事件区间与加速时间为自动候选边界，图中提供前后各60个交易日，必须人工审核后才可形成最终数据库。", "", "候选 CSV 中保留 `review_status=pending`。审核人可在 `candidate_review_log.csv` 中填写 `approved`、`modified` 或 `rejected`、审核人、日期和说明；随后运行 `finalize` 生成最终事件库。", ""])
    target.write_text("\n".join(text), encoding="utf-8")


def rebuild_from_saved(config: dict, base_dir: Path) -> dict[str, object]:
    paths = config["paths"]
    raw_dir = _resolve(base_dir, paths["raw_dir"])
    panel_path = raw_dir / "akshare_sina_contract_panel.parquet"
    if not panel_path.exists():
        panel_path = raw_dir / "tradingview_price_only_contract_panel.parquet"
    if not panel_path.exists():
        raise FileNotFoundError(f"No saved contract panel found under {raw_dir}")
    panel = pd.read_parquet(panel_path)
    # Rebuild uses already retrieved data; retain the same project output structure.
    temp_source = _SavedPanelSource(panel)
    return _build_from_panel(config, base_dir, temp_source)


class _SavedPanelSource:
    def __init__(self, panel: pd.DataFrame):
        self.panel = panel


def _build_from_panel(config: dict, base_dir: Path, source: _SavedPanelSource) -> dict[str, object]:
    # Reuse the deterministic portion of the pipeline without re-requesting providers.
    instrument = config["instrument"]
    continuous, rolls = build_continuous_series(source.panel, int(config["continuous"]["dominance_sessions"]))
    processed_dir = _resolve(base_dir, config["paths"]["processed_dir"])
    instrument_dir = _resolve(base_dir, config["paths"]["instrument_dir"])
    reports_dir = _resolve(base_dir, config["paths"]["reports_dir"])
    processed_dir.mkdir(parents=True, exist_ok=True)
    q1_dir = instrument_dir / "01_Extreme_Market_Database"
    q1_dir.mkdir(parents=True, exist_ok=True)
    continuous.to_parquet(processed_dir / "continuous_main_raw_and_adjusted.parquet", index=False)
    rolls.to_csv(processed_dir / "roll_adjustments.csv", index=False, encoding="utf-8-sig")
    term = build_term_structure(source.panel)
    term.to_csv(processed_dir / "term_structure_top_open_interest.csv", index=False, encoding="utf-8-sig")
    reports_dir.mkdir(parents=True, exist_ok=True)
    build_gap_audit(source.panel).to_csv(reports_dir / "trading_date_gap_audit.csv", index=False, encoding="utf-8-sig")
    build_price_jump_audit(continuous).to_csv(reports_dir / "price_jump_audit.csv", index=False, encoding="utf-8-sig")
    cfg = config["episodes"]
    candidates, trigger_map, thresholds = scan_extreme_episodes(
        continuous,
        instrument_name=instrument["name_zh"],
        product_code=instrument["product_code"],
        horizons=tuple(cfg["horizons"]),
        lower_quantile=cfg["lower_quantile"],
        upper_quantile=cfg["upper_quantile"],
        merge_gap_sessions=cfg["merge_gap_sessions"],
    )
    (q1_dir / "episode_charts").mkdir(exist_ok=True)
    (q1_dir / "episode_paths").mkdir(exist_ok=True)
    candidates.to_csv(q1_dir / "extreme_episodes_candidates.csv", index=False, encoding="utf-8-sig")
    trigger_map.to_csv(q1_dir / "episode_trigger_windows.csv", index=False, encoding="utf-8-sig")
    thresholds.to_csv(q1_dir / "tail_thresholds.csv", index=False, encoding="utf-8-sig")
    for _, episode in candidates.iterrows():
        draw_episode_chart(continuous, episode, q1_dir / episode.chart_path, int(cfg["chart_context_sessions"]))
        start, end = pd.Timestamp(episode.event_start_date), pd.Timestamp(episode.event_end_date)
        dates = pd.to_datetime(continuous.trade_date)
        left = max(0, int(dates.searchsorted(start)) - int(cfg["chart_context_sessions"]))
        right = min(len(continuous), int(dates.searchsorted(end, side="right")) + int(cfg["chart_context_sessions"]))
        path = continuous.iloc[left:right].copy()
        path["episode_id"] = episode.episode_id
        path["in_candidate_interval"] = path.trade_date.between(start, end)
        path.to_csv(q1_dir / episode.path_csv, index=False, encoding="utf-8-sig")
    quality = inspect_contract_panel(source.panel)
    quality.update(inspect_continuous(continuous, rolls))
    quality.update(
        {
            "instrument": instrument["name_zh"],
            "cutoff_exclusive": instrument["cutoff_exclusive"],
            "candidate_episode_count": len(candidates),
            "pending_review_count": int((candidates.review_status == "pending").sum()) if "review_status" in candidates else 0,
            "term_structure_rows": len(term),
        }
    )
    pd.DataFrame([quality]).to_csv(reports_dir / "data_quality_summary.csv", index=False, encoding="utf-8-sig")
    source_audit_path = reports_dir / "data_source_attempts.csv"
    saved_audits = pd.read_csv(source_audit_path, encoding="utf-8-sig") if source_audit_path.exists() else pd.DataFrame()
    _write_coverage_report(reports_dir / "q1_coverage_report.md", quality, saved_audits, thresholds, candidates)
    return {"status": "rebuilt", "continuous_rows": len(continuous), "candidates": len(candidates)}


def finalize_reviewed_candidates(config: dict, base_dir: Path) -> dict[str, object]:
    q1_dir = _resolve(base_dir, config["paths"]["instrument_dir"]) / "01_Extreme_Market_Database"
    candidate_path = q1_dir / "extreme_episodes_candidates.csv"
    review_path = q1_dir / "candidate_review_log.csv"
    candidates = pd.read_csv(candidate_path, encoding="utf-8-sig")
    reviews = pd.read_csv(review_path, encoding="utf-8-sig").drop_duplicates("episode_id", keep="last")
    merged = candidates.drop(columns=[column for column in ("review_status", "review_decision", "reviewer", "review_date", "review_notes") if column in candidates.columns]).merge(
        reviews, on="episode_id", how="left", validate="one_to_one"
    )
    unresolved = merged.review_status.fillna("pending").eq("pending")
    if unresolved.any():
        ids = ", ".join(merged.loc[unresolved, "episode_id"].astype(str))
        raise ValueError(f"All candidates must be reviewed before finalization. Pending: {ids}")
    allowed = {"approved", "modified", "rejected"}
    invalid = set(merged.review_status.dropna().astype(str)) - allowed
    if invalid:
        raise ValueError(f"Invalid review statuses: {sorted(invalid)}")
    final = merged.loc[merged.review_status.isin(["approved", "modified"])].copy()
    final.to_csv(q1_dir / "extreme_episodes.csv", index=False, encoding="utf-8-sig")
    return {"status": "finalized", "approved_or_modified": len(final), "rejected": int((merged.review_status == "rejected").sum()), "output": str(q1_dir / "extreme_episodes.csv")}
