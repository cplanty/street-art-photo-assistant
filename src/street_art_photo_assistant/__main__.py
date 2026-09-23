"""Command-line entry point."""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import load_config
from .web import create_app
from .workflow import run_offline_clustering


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Street Art Photo Assistant")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("serve", "cluster"),
        default="serve",
    )
    parser.add_argument(
        "--config", type=Path, default=Path("config.local.json")
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("_runs") / "manual",
        help="Cluster command output directory",
    )
    parser.add_argument(
        "--visual",
        action="store_true",
        help="Apply optional local OpenCV sub-clustering",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config_path = args.config.expanduser().resolve()
    config = load_config(config_path)
    if args.command == "cluster":
        result = run_offline_clustering(
            config,
            config_root=config_path.parent,
            output_directory=args.output.expanduser().resolve(),
            visual=args.visual,
        )
        print(
            f"{result['selected']} selected from {result['scanned']} scanned; "
            f"{result['clusters']} cluster(s)"
        )
        print(result["output_directory"])
        return
    app = create_app(config, config_path)
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
