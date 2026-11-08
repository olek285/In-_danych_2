"""Show raw source data exactly as stored in bronze - without any new request.

Usage examples:
    uv run python scripts/inspect_sources.py                    # all sources, latest partition
    uv run python scripts/inspect_sources.py --source krs_current --key 0000028860
    uv run python scripts/inspect_sources.py --source krs_current --flat   # dotted paths
    uv run python scripts/inspect_sources.py --source opensanctions --rows 5

For JSON sources it prints, per record, the request URL, HTTP status, size and
whether the body is valid JSON, then the key tree merged over all records
(types, list lengths, one example value). For CSV sources it prints the
stored metadata, the column names and the first rows.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kyb.config import load_settings
from kyb.storage import BronzeStore

JSON_SOURCES = ("krs_current", "krs_full", "vat_whitelist")
CSV_SOURCES = ("opensanctions",)


# ---------------------------------------------------------------- JSON shape
@dataclass
class Shape:
    types: Counter = field(default_factory=Counter)
    keys: dict[str, Shape] = field(default_factory=dict)
    items: Shape | None = None
    lengths: list[int] = field(default_factory=list)
    example: Any = None

    def observe(self, value: Any) -> None:
        self.types[type_name(value)] += 1
        if isinstance(value, dict):
            for key, item in value.items():
                self.keys.setdefault(key, Shape()).observe(item)
        elif isinstance(value, list):
            self.lengths.append(len(value))
            self.items = self.items or Shape()
            for item in value:
                self.items.observe(item)
        elif self.example is None and value not in (None, ""):
            self.example = value


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    return {dict: "object", list: "list", str: "str", bool: "bool", int: "int", float: "float"}.get(
        type(value), type(value).__name__
    )


def describe(shape: Shape, width: int) -> str:
    kinds = []
    for kind in shape.types:
        if kind == "list":
            lo, hi = min(shape.lengths), max(shape.lengths)
            kinds.append(f"list[{lo}]" if lo == hi else f"list[{lo}..{hi}]")
        else:
            kinds.append(kind)
    text = "|".join(kinds)
    if shape.example is not None:
        if isinstance(shape.example, str):
            example = shape.example.replace("\n", "\\n")
            if len(example) > width:
                example = example[: width - 1] + "…"
            text += f"  e.g. {example!r}"
        else:
            text += f"  e.g. {shape.example}"
    return text


def render_tree(shape: Shape, name: str, depth: int, max_depth: int, width: int, out: list[str]) -> None:
    out.append(f"{'  ' * depth}{name}: {describe(shape, width)}")
    if depth >= max_depth:
        if shape.keys or shape.items:
            out.append(f"{'  ' * (depth + 1)}… (deeper levels hidden, use --depth)")
        return
    for key, child in shape.keys.items():
        render_tree(child, key, depth + 1, max_depth, width, out)
    if shape.items is not None and (shape.items.keys or shape.items.items):
        render_tree(shape.items, "[]", depth + 1, max_depth, width, out)


def render_flat(shape: Shape, path: str, width: int, out: list[str]) -> None:
    if not shape.keys and not (shape.items and (shape.items.keys or shape.items.items)):
        out.append(f"{path} = {describe(shape, width)}")
    for key, child in shape.keys.items():
        render_flat(child, f"{path}.{key}" if path else key, width, out)
    if shape.items is not None:
        render_flat(shape.items, f"{path}[]", width, out)


# ------------------------------------------------------------------ helpers
def latest_partition(base: Path) -> Path | None:
    parts = sorted(p for p in base.glob("ingest_date=*") if p.is_dir()) if base.is_dir() else []
    return parts[-1] if parts else None


def body_kind(payload: str) -> tuple[str, Any]:
    try:
        return "json", json.loads(payload)
    except ValueError:
        return ("NOT JSON (HTML page)" if payload.lstrip().startswith("<") else "NOT JSON"), None


def inspect_json_source(store: BronzeStore, source: str, args: argparse.Namespace) -> None:
    base = store.root / source
    partition = base / f"ingest_date={args.date}" if args.date else latest_partition(base)
    print(f"\n=== {source} ===")
    if partition is None or not partition.is_dir():
        print(f"  no data in {base} - run 'uv run kyb-ingest {source.split('_')[0]}' first")
        return
    envelopes = [
        json.loads(line)
        for part in sorted(partition.glob("part-*.jsonl"))
        for line in part.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if args.key:
        envelopes = [e for e in envelopes if e["key"] == args.key]
    print(f"partition: {partition} ({len(envelopes)} record(s))")
    print(f"{'key':<14} {'status':>6} {'bytes':>8} {'redacted':>8}  {'body':<22} {'ingested_at':<26} url")
    shape = Shape()
    latest: dict[str, dict[str, Any]] = {}
    for env in envelopes:
        kind, data = body_kind(env["payload"])
        key = env["key"] if len(env["key"]) <= 14 else env["key"][:11] + "..."
        size = len(env["payload"].encode("utf-8"))
        print(f"{key:<14} {env['http_status']:>6} {size:>8} {env.get('redacted_values', '-'):>8}  "
              f"{kind:<22} {env['ingested_at']:<26} {env['url']}")
        if data is not None and env["http_status"] == 200:
            latest[env["key"]] = data  # later part files override earlier ones
    for data in latest.values():
        shape.observe(data)
    if not latest:
        print("  (no valid HTTP 200 JSON body to describe)")
        return
    print(f"\n--- structure merged over {len(latest)} latest HTTP 200 JSON body(ies) ---")
    out: list[str] = []
    if args.flat:
        render_flat(shape, "", args.width, out)
    else:
        render_tree(shape, "<root>", 0, args.depth, args.width, out)
    print("\n".join(out))


def inspect_opensanctions(store: BronzeStore, args: argparse.Namespace) -> None:
    print("\n=== opensanctions ===")
    metas = sorted((store.root / "opensanctions").glob("ingest_date=*/*/*/_metadata.json"))
    if not metas:
        print("  no data - run 'uv run kyb-ingest sanctions' first")
        return
    newest: dict[str, tuple[dict[str, Any], Path]] = {}
    for path in metas:
        meta = json.loads(path.read_text(encoding="utf-8"))
        if args.key and meta["key"] != args.key:
            continue
        if meta["key"] not in newest or meta["ingested_at"] >= newest[meta["key"]][0]["ingested_at"]:
            newest[meta["key"]] = (meta, path)
    for dataset, (meta, path) in sorted(newest.items()):
        orig, kept = meta["original"], meta["stored"]
        print(f"\n--- {dataset} (version {meta['dataset_version']}) ---")
        print(f"url:       {meta['url']}  -> HTTP {meta['http_status']}")
        print(f"index:     {meta['index_url']}")
        print(f"original:  {orig['size_bytes']} B, {orig['rows']} rows, SHA-1 "
              f"{'matches' if orig['sha1'] == orig['sha1_published'] else 'DIFFERS FROM'} index.json")
        print(f"schemas:   {orig['schema_counts']}")
        print(f"stored:    {kept['size_bytes']} B, {kept['rows']} rows ({', '.join(kept['kept_schemas'])}); "
              f"dropped {kept['dropped_rows']}")
        print(f"columns:   {meta['columns']}")
        csv_path = path.parent / meta["file"]
        with csv_path.open(encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            next(reader)
            for i, row in enumerate(reader):
                if i >= args.rows:
                    break
                cells = [c if len(c) <= args.width else c[: args.width - 1] + "…" for c in row]
                print(f"row {i + 1}:     {dict(zip(meta['columns'], cells))}")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Polish letters on Windows consoles
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=(*JSON_SOURCES, *CSV_SOURCES, "all"), default="all")
    parser.add_argument("--key", help="only this key (KRS number, NIP batch or dataset name)")
    parser.add_argument("--date", help="partition YYYY-MM-DD (default: latest)")
    parser.add_argument("--depth", type=int, default=5, help="JSON tree depth (default 5)")
    parser.add_argument("--flat", action="store_true", help="print dotted JSON paths instead of a tree")
    parser.add_argument("--rows", type=int, default=3, help="CSV rows to show (default 3)")
    parser.add_argument("--width", type=int, default=60, help="truncate example values (default 60)")
    parser.add_argument("--bronze", type=Path, help="bronze directory (default from settings.yaml)")
    args = parser.parse_args(argv)

    store = BronzeStore(args.bronze or load_settings().bronze_dir)
    sources = (*JSON_SOURCES, *CSV_SOURCES) if args.source == "all" else (args.source,)
    for source in sources:
        if source in CSV_SOURCES:
            inspect_opensanctions(store, args)
        else:
            inspect_json_source(store, source, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
