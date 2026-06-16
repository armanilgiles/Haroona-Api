from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from app.curation.shopify_collection import (
    CollectionScanOptions,
    build_candidate_payloads,
    scan_and_save_shopify_collection,
)
from app.database import SessionLocal


DEFAULT_NOBODYS_CHILD_MATERRA_URL = "https://www.nobodyschild.com/en-us/collections/materra"


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan a Shopify collection into Haroona product candidates.")
    parser.add_argument("--url", default=DEFAULT_NOBODYS_CHILD_MATERRA_URL)
    parser.add_argument("--merchant", default="Nobody's Child")
    parser.add_argument("--city", default="london")
    parser.add_argument("--category", default=None)
    parser.add_argument("--source", default="shopify")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="Print candidates without writing to the database.")
    args = parser.parse_args()

    options = CollectionScanOptions(
        source_url=args.url,
        merchant_name=args.merchant,
        target_city_slug=args.city,
        normalized_category=args.category,
        source=args.source,
        limit=args.limit,
    )

    if args.dry_run:
        payloads = build_candidate_payloads(options)
        print(
            json.dumps(
                [
                    {
                        **asdict(item),
                        "price_amount": str(item.price_amount) if item.price_amount is not None else None,
                    }
                    for item in payloads
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return

    db = SessionLocal()
    try:
        result = scan_and_save_shopify_collection(db, options)
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
