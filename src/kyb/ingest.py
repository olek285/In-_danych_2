"""Command line entry point: ``uv run kyb-ingest <source> [options]``.

Exit codes: 0 = success, 1 = some requests failed (see log), 2 = bad input.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

from kyb.config import Settings, load_settings
from kyb.http import HttpClient
from kyb.ingestion.krs import SOURCE_BY_ENDPOINT, ingest_krs
from kyb.ingestion.report import IngestReport
from kyb.ingestion.vat import ingest_vat, nips_from_krs_bronze
from kyb.logging_setup import setup_logging
from kyb.nip import is_valid_nip, normalize_nip
from kyb.quota import DailyQuota
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


def vat_quota(settings: Settings) -> DailyQuota:
    cfg = settings.source("vat")
    return DailyQuota(
        settings.state_dir / "vat_whitelist_quota.json",
        limit=cfg["daily_search_limit"],
        safety_margin=cfg.get("safety_margin", 0),
    )


def cmd_vat(args: argparse.Namespace, settings: Settings) -> list[IngestReport]:
    cfg = settings.source("vat")
    store = BronzeStore(settings.bronze_dir)
    if args.nip:
        bad = [n for n in args.nip if not is_valid_nip(n)]
        if bad:
            raise ValueError(f"invalid NIP checksum: {', '.join(bad)}")
        nips = [normalize_nip(n) for n in args.nip]
    else:
        nips, problems = nips_from_krs_bronze(store)
        for problem in problems:
            log.warning("%s", problem)
        if not nips:
            raise ValueError("no NIPs found in bronze KRS extracts - run 'kyb-ingest krs' first")
    report = ingest_vat(
        nips,
        client=HttpClient.from_settings(settings.http),
        store=store,
        quota=vat_quota(settings),
        base_url=cfg["base_url"],
        batch_size=cfg["batch_size"],
        max_retries=cfg.get("max_retries", 1),
        query_date=date.fromisoformat(args.date) if args.date else None,
        force=args.force,
        dry_run=args.dry_run,
    )
    return [report]


def cmd_quota(args: argparse.Namespace, settings: Settings) -> list[IngestReport]:
    print(f"VAT White List quota - {vat_quota(settings).status()}")
    return []


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kyb-ingest", description="Fetch raw source data into bronze.")
    parser.add_argument("--log-level", default=None, help="DEBUG, INFO, WARNING (default: KYB_LOG_LEVEL or INFO)")
    sub = parser.add_subparsers(dest="command", required=True)

    krs = sub.add_parser("krs", help="KRS extracts for the watchlist (or --krs numbers)")
    krs.add_argument("--krs", nargs="+", metavar="NUMBER", help="ingest these numbers instead of the watchlist")
    krs.add_argument("--endpoint", choices=sorted(SOURCE_BY_ENDPOINT), help="default from settings.yaml")
    krs.add_argument("--force", action="store_true", help="re-fetch numbers already ingested today")
    krs.set_defaults(func=cmd_krs)

    vat = sub.add_parser("vat", help="VAT White List status for NIPs from the stored KRS extracts")
    vat.add_argument("--dry-run", action="store_true", help="only show how many requests would be used")
    vat.add_argument("--date", help="status as of YYYY-MM-DD (default: today)")
    vat.add_argument("--nip", nargs="+", metavar="NIP", help="query these NIPs instead of the KRS ones")
    vat.add_argument("--force", action="store_true", help="re-query NIPs already answered for that date")
    vat.set_defaults(func=cmd_vat)

    quota = sub.add_parser("quota", help="show today's VAT White List request counter")
    quota.set_defaults(func=cmd_quota)
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
