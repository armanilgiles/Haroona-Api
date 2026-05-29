from __future__ import annotations

import argparse

from app.catalog.price_refresh import refresh_products_from_normalized
from app.database import SessionLocal


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh promoted Haroona product prices from normalized feed data."
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Optional product source to refresh, e.g. awin. Defaults to all sources.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max number of products to refresh.",
    )
    parser.add_argument(
        "--keep-out-of-stock-active",
        action="store_true",
        help="Do not deactivate products when the feed says they are out of stock.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the refresh and print counts without committing changes.",
    )

    args = parser.parse_args()

    db = SessionLocal()
    try:
        counts = refresh_products_from_normalized(
            db,
            source=args.source,
            limit=args.limit,
            deactivate_out_of_stock=not args.keep_out_of_stock_active,
        )

        if args.dry_run:
            db.rollback()
            print({"status": "dry_run", **counts})
            return

        db.commit()
        print({"status": "ok", **counts})

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    main()
