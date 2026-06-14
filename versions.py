"""Inspect LanceDB version history and demonstrate time-travel.

Every write to LanceDB creates a new version automatically (zero-copy).
Each `python index.py` run also tags the resulting version, so you can
open any historical snapshot like a git tag.

Usage:
  python versions.py                       # list tags + current version
  python versions.py --tag <tag-name>      # show what the table looked like at that tag
"""

import argparse

import lancedb

DB_PATH = "data/lancedb"
TABLE = "jobs"


def main() -> None:
    parser = argparse.ArgumentParser(description="Browse LanceDB version history.")
    parser.add_argument("--tag", help="open the table at a specific tag (e.g. ingest-2026-05-20-1430)")
    parser.add_argument("--limit", type=int, default=3, help="rows to preview when checking out a tag")
    args = parser.parse_args()

    db = lancedb.connect(DB_PATH)
    table = db.open_table(TABLE)

    if args.tag:
        # Time-travel: checkout mutates the handle to point at the historical version
        snapshot = db.open_table(TABLE)
        snapshot.checkout(args.tag)
        print(f"\n📌 snapshot '{args.tag}'  ·  version {snapshot.version}  ·  {snapshot.count_rows()} rows")
        df = snapshot.to_pandas().head(args.limit)
        for _, row in df.iterrows():
            print(f"  • {row['title']:<55} — {row['company']}")
        return

    # Default: list tags + current state
    current = table.version
    rows = table.count_rows()
    print(f"\n📊 table 'jobs'  ·  current version: {current}  ·  {rows} rows")

    tags = table.tags.list()
    print(f"\n🏷  tags ({len(tags)}):")
    if not tags:
        print("  (none — run `python index.py` to create the first tagged snapshot)")
    else:
        for name in sorted(tags.keys() if isinstance(tags, dict) else tags):
            try:
                v = table.tags.get_version(name)
                marker = "  ← current" if v == current else ""
                print(f"  • {name:<32} → version {v}{marker}")
            except Exception as e:
                print(f"  • {name:<32} → (error: {e})")

    print("\n  travel back with: `python versions.py --tag <name>`")


if __name__ == "__main__":
    main()
