from __future__ import annotations

import argparse

from sqlalchemy import or_

from app.database import SessionLocal
from app.media.product_images import (
    optimize_and_upload_product_image,
)
from app.models import Product


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create CDN-hosted WebP thumbnails for Haroona products."
    )
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--product-id", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-width", type=int, default=640)
    parser.add_argument("--max-height", type=int, default=960)
    parser.add_argument("--quality", type=int, default=72)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    succeeded = 0
    failed = 0

    try:
        query = (
            db.query(Product)
            .filter(Product.is_active.is_(True))
            .filter(Product.product_image_url.isnot(None))
            .filter(Product.product_image_url != "")
            .order_by(Product.id.asc())
        )

        if args.product_id:
            query = query.filter(Product.id == args.product_id)
        elif not args.force:
            query = query.filter(
                or_(
                    Product.optimized_product_image_url.is_(None),
                    Product.optimized_product_image_url == "",
                )
            )

        products = query.limit(max(1, args.limit)).all()
        if not products:
            print("No products need image optimization.")
            return 0

        for product in products:
            try:
                result = optimize_and_upload_product_image(
                    product_id=product.id,
                    source_url=product.product_image_url,
                    max_width=args.max_width,
                    max_height=args.max_height,
                    quality=args.quality,
                )
                product.optimized_product_image_url = result.url
                product.product_image_width = result.width
                product.product_image_height = result.height
                db.add(product)
                db.commit()

                succeeded += 1
                print(
                    f"[ok] product={product.id} "
                    f"{result.width}x{result.height} "
                    f"{result.byte_count / 1024:.1f}KB"
                )
            except Exception as exc:
                db.rollback()
                failed += 1
                print(f"[failed] product={product.id}: {exc}")

        print(f"Finished: {succeeded} optimized, {failed} failed.")
        return 1 if failed and not succeeded else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
