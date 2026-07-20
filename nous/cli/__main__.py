"""Nous CLI — Data management tools.

Usage examples::

    python -m nous.cli import  --persona herta   --input data/herta.zip
    python -m nous.cli export  --persona herta   --output backup/herta.jsonl
    python -m nous.cli stats   --persona herta
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from nous.config.settings import Settings
from nous.infrastructure.sqlite.connection import SQLiteConnection
from nous.migration.exporters.jsonl_exporter import JSONLExporter
from nous.migration.importers.jsonl_importer import JSONLImporter
from nous.migration.importers.legacy_importer import LegacyImporter


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="nous.cli",
        description="Nous CLI — data import / export / migration utilities",
    )
    subparsers = parser.add_subparsers(dest="command")

    # -- import --------------------------------------------------------
    import_parser = subparsers.add_parser("import", help="Import data")
    import_parser.add_argument("--persona", required=True)
    import_parser.add_argument(
        "--input",
        required=True,
        help="Path to zip file, directory, or JSONL file",
    )
    import_parser.add_argument(
        "--format",
        default="auto",
        choices=["auto", "legacy", "jsonl"],
        help="Source format (default: auto-detect from extension)",
    )

    # -- export --------------------------------------------------------
    export_parser = subparsers.add_parser("export", help="Export data")
    export_parser.add_argument("--persona", required=True)
    export_parser.add_argument("--output", required=True)
    export_parser.add_argument(
        "--format",
        default="jsonl",
        choices=["jsonl"],
    )

    # -- stats ---------------------------------------------------------
    stats_parser = subparsers.add_parser("stats", help="Show persona statistics")
    stats_parser.add_argument("--persona", required=True)

    # -- auto-import ---------------------------------------------------
    auto_import_parser = subparsers.add_parser("auto-import", help="Auto-import all .zip files from a directory")
    auto_import_parser.add_argument(
        "--import-dir",
        required=True,
        help="Directory to scan for .zip files",
    )

    # keep linters happy — parsers are used via subparsers
    _ = (import_parser, export_parser, stats_parser, auto_import_parser)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    settings = Settings()

    handlers = {
        "import": _handle_import,
        "export": _handle_export,
        "stats": _handle_stats,
        "auto-import": _handle_auto_import,
    }
    handlers[args.command](args, settings)


# ------------------------------------------------------------------
# Sub-command handlers
# ------------------------------------------------------------------


def _handle_import(args: argparse.Namespace, settings: Settings) -> None:
    conn = SQLiteConnection(settings.persona_dir, args.persona)
    conn.initialize_schema()

    input_path = Path(args.input)

    fmt = ("jsonl" if input_path.suffix == ".jsonl" else "legacy") if args.format == "auto" else args.format

    if fmt == "legacy":
        importer = LegacyImporter(conn, args.persona)
        result = (
            importer.import_from_zip(str(input_path))
            if input_path.suffix == ".zip"
            else importer.import_from_directory(str(input_path))
        )
    elif fmt == "jsonl":
        importer_jsonl = JSONLImporter()
        result = importer_jsonl.import_file(str(input_path), conn, args.persona)
    else:
        print(f"Unsupported format: {fmt}")
        sys.exit(1)

    if result.is_ok:
        print(f"Import successful for persona '{args.persona}':")
        for table, count in result.value.items():
            print(f"  {table}: {count} records")
    else:
        print(f"Import failed: {result.error}")
        sys.exit(1)

    conn.close()


def _handle_export(args: argparse.Namespace, settings: Settings) -> None:
    conn = SQLiteConnection(settings.persona_dir, args.persona)

    exporter = JSONLExporter()
    result = exporter.export_persona(conn, args.persona, args.output)

    if result.is_ok:
        print(f"Exported {result.value} records to {args.output}")
    else:
        print(f"Export failed: {result.error}")
        sys.exit(1)

    conn.close()


def _handle_stats(args: argparse.Namespace, settings: Settings) -> None:
    conn = SQLiteConnection(settings.persona_dir, args.persona)
    db = conn.get_memory_db()
    inv = conn.get_inventory_db()

    print(f"=== Persona: {args.persona} ===")

    _print_count(db, "memories", "Memories")
    _print_count(db, "memory_strength", "Memory strength records")
    _print_count(db, "memory_blocks", "Memory blocks")
    _print_count(db, "emotion_history", "Emotion records")
    _print_count(db, "context_state", "Context state entries")
    _print_count(db, "goals", "Goals")
    _print_count(db, "promises", "Promises")
    _print_count(inv, "items", "Items")
    _print_count(inv, "equipment_slots", "Equipment slots")
    _print_count(inv, "equipment_history", "Equipment history")

    conn.close()


def _handle_auto_import(args: argparse.Namespace, settings: Settings) -> None:
    """Run auto-import for all .zip files found in the given directory."""
    from nous.application.auto_import import run_auto_import

    results = run_auto_import(settings, import_dir=args.import_dir)
    if not results:
        print("No .zip files found in", args.import_dir)
        return

    for persona, counts in results.items():
        print(f"Imported persona '{persona}':")
        for table, count in counts.items():
            print(f"  {table}: {count} records")


def _print_count(db, table: str, label: str) -> None:
    try:
        count = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608  # nosec B608
        print(f"  {label}: {count}")
    except Exception:  # noqa: BLE001
        print(f"  {label}: (table not found)")


if __name__ == "__main__":
    main()
