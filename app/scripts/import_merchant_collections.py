from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.curation.merchant_collections import (
    DEFAULT_COLLECTION_SEED_PATH,
    import_collection_records,
    load_collection_seed,
)
from app.database import SessionLocal


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import Haroona merchant collection URLs idempotently.",
    )
    parser.add_argument(
        "--seed",
        type=Path,
        default=DEFAULT_COLLECTION_SEED_PATH,
        help="Path to a versioned merchant collection JSON seed.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report changes without committing them.",
    )
    parser.add_argument(
        "--include-manual-review",
        action="store_true",
        help="Also import records explicitly marked for manual review.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    seed = load_collection_seed(args.seed)
    import_batch = str(seed.get("import_batch") or args.seed.stem)
    db = SessionLocal()
    try:
        report = import_collection_records(
            db,
            seed["records"],
            import_batch=import_batch,
            include_manual_review=args.include_manual_review,
            dry_run=args.dry_run,
        )
    finally:
        db.close()
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
