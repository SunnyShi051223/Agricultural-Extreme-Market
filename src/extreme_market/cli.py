from __future__ import annotations

import argparse
import json
from pathlib import Path

from extreme_market.pipeline import build_from_sources, finalize_reviewed_candidates, load_config, rebuild_from_saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Q1 instrument-specific extreme-market database")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("build", "download sources and build deterministic Q1 outputs"),
        ("rebuild", "rebuild deterministic outputs from saved raw source data"),
        ("finalize", "write the final database after all candidate review statuses are completed"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--config", required=True, help="path to instrument YAML configuration")
    args = parser.parse_args()
    config, base_dir = load_config(args.config)
    if args.command == "build":
        result = build_from_sources(config, base_dir)
    elif args.command == "rebuild":
        result = rebuild_from_saved(config, base_dir)
    else:
        result = finalize_reviewed_candidates(config, base_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
