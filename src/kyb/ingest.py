"""Command line entry point: ``uv run kyb-ingest <source> [options]``.

Exit codes: 0 = success, 1 = some requests failed (see log), 2 = bad input.
"""

from __future__ import annotations

import argparse
import logging
import sys

from kyb.config import Settings, load_settings
from kyb.http import HttpClient
from kyb.ingestion.krs import SOURCE_BY_ENDPOINT, ingest_krs
from kyb.ingestion.report import IngestReport
from kyb.logging_setup import setup_logging
from kyb.storage import BronzeStore
from kyb.watchlist import normalize_krs, read_watchlist, unique

log = logging.getLogger("kyb.ingest")


def _krs_numbers(settings: Settings, explicit: list[str] | None) -> list[str]:
    if explicit:
        return unique(normalize_krs(k) for k in explicit)
    numbers = read_watchlist(settings.watchlist_path)
    if not numbers:
        raise ValueError(f"watchlist {settings.watchlist_path} is empty - add KRS numbers first")
    return numbers


def cmd_krs(args: argparse.Namespace, settings: Settings) -> list[IngestReport]:
    cfg = settings.source("krs")
    client = HttpClient.from_settings(settings.http)
    report = ingest_krs(
        _krs_numbers(settings, args.krs),
        client=client,
        store=BronzeStore(settings.bronze_dir),
        base_url=cfg["base_url"],
        endpoint=args.endpoint or cfg["endpoint"],
        register=cfg["register"],
        force=args.force,
        min_interval_s=cfg.get("min_interval_seconds", 1.0),
    )
    return [report]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kyb-ingest", description="Fetch raw source data into bronze.")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING (default: KYB_LOG_LEVEL or INFO)")
    sub = parser.add_subparsers(dest="command", required=True)

    krs = sub.add_parser("krs", help="KRS extracts for the watchlist (or --krs numbers)")
    krs.add_argument("--krs", nargs="+", metavar="NUMBER", help="ingest these numbers instead of the watchlist")
    krs.add_argument("--endpoint", choices=sorted(SOURCE_BY_ENDPOINT), help="default from settings.yaml")
    krs.add_argument("--force", action="store_true", help="re-fetch numbers already ingested today")
    krs.set_defaults(func=cmd_krs)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = load_settings()
    setup_logging(settings.log_dir, args.log_level)
    try:
        reports = args.func(args, settings)
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    for report in reports:
        print(report.summary())
    return 0 if all(r.ok for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
