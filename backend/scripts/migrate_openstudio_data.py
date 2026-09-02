from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.data_migration import migrate_default_data_dir


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Safely adopt an existing Open Studio data directory as Mosael data."
    )
    parser.add_argument(
        "--home",
        type=Path,
        default=Path.home(),
        help="Home directory containing .open-studio and .mosael (default: current home).",
    )
    args = parser.parse_args()

    result = migrate_default_data_dir(args.home.expanduser().resolve())
    print(f"status={result.status}")
    print(f"target={result.target}")
    if result.source is not None:
        print(f"source={result.source}")
    if result.backup is not None:
        print(f"backup={result.backup}")
    if result.source_preserved:
        print("source_preserved=true")
    return 0 if result.status in {"migrated", "copied", "no-legacy-data"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
