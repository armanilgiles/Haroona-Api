from __future__ import annotations

import argparse
from pathlib import Path

from app.catalog.published_product_refresh import ProductRefreshReport, ProductRefreshService
from app.database import SessionLocal


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check published Haroona products against their original merchant "
            "pages. Dry run is the default."
        )
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Inspect and report without changing the database (default).",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply only high-confidence price changes and refresh metadata.",
    )
    parser.add_argument(
        "--product-id",
        type=int,
        default=None,
        help="Check one published database product.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Check at most this many published products.",
    )
    parser.add_argument(
        "--merchant",
        default=None,
        help='Filter by merchant/brand name, for example "Rainbow Shops".',
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Check every published product instead of the default 20-product sample.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path for the machine-readable JSON report.",
    )
    return parser


def _validate_args(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
) -> None:
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    if args.all and args.limit is not None:
        parser.error("--all and --limit cannot be used together")
    if args.all and args.product_id is not None:
        parser.error("--all and --product-id cannot be used together")
    if args.apply and not (
        args.product_id is not None
        or args.limit is not None
        or args.merchant
    ):
        parser.error(
            "--apply requires --product-id, --limit, or --merchant. "
            "A full-catalog apply is intentionally disabled in Phase 2."
        )
    if args.apply and args.all:
        parser.error(
            "Full-catalog --apply is intentionally disabled in Phase 2. "
            "Review a dry-run report, then use a controlled selector."
        )


def _print_report(report: ProductRefreshReport) -> None:
    summary = report.summary
    print(f"Mode: {report.mode}")
    print(
        "Published products checked: "
        f"{summary['published_products_checked']}"
    )
    print(f"Unchanged: {summary['unchanged']}")
    print(f"Price changes found: {summary['price_changed']}")
    print(f"Available: {summary['available']}")
    print(f"Likely unavailable: {summary['likely_unavailable']}")
    print(f"Product unavailable: {summary['product_unavailable']}")
    print(f"Affiliate links broken: {summary['affiliate_link_broken']}")
    print(f"Blocked or unknown: {summary['blocked_or_unknown']}")
    print(f"Temporary failures: {summary['temporary_failure']}")
    print(f"Parse failures: {summary['parse_failure']}")

    for item in report.results:
        print()
        print(
            f"[{item.product_id}] {item.merchant} — {item.stored_title}"
        )
        print(
            f"  {item.refresh_status.value} ({item.confidence}): "
            f"{item.reason}"
        )
        print(
            "  price: "
            f"{item.stored_price} -> {item.detected_price} "
            f"{item.detected_currency or item.currency}"
        )
        print(f"  original: {item.original_url}")
        print(f"  final: {item.final_url}")
        if item.affiliate_url:
            print(
                f"  affiliate: {item.affiliate_status} "
                f"({item.affiliate_final_url or item.affiliate_url})"
            )
        print(
            f"  would update: {item.would_update}; "
            f"would flag for review: {item.would_flag_for_review}"
        )


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(parser, args)
    apply = bool(args.apply)
    default_limit = None if args.all else (args.limit or 20)

    db = SessionLocal()
    try:
        service = ProductRefreshService(db)
        products = service.select_products(
            product_id=args.product_id,
            merchant=args.merchant,
            limit=default_limit,
            all_products=args.all,
        )
        report = service.run(products, apply=apply)
        if apply:
            db.commit()
        else:
            # The service is mutation-free in dry-run mode. Rollback is an
            # additional guard against future accidental session changes.
            db.rollback()

        _print_report(report)
        if args.output:
            output_path = Path(args.output).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report.to_json() + "\n", encoding="utf-8")
            print(f"\nJSON report: {output_path}")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
