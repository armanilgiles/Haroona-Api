from __future__ import annotations

from app.catalog.manual_seed_registry import SEED_LIST


def main() -> None:
    for seed in SEED_LIST:
        print(f"\n=== {seed.key} | {seed.brand_name} | {seed.city_name} | {len(seed.products)} products ===")
        for item in seed.products:
            print(f"- {item['name']}")
            print(f"  affiliate_url: {item['affiliate_url']}")
            print(f"  merchant_url:  {item['merchant_url']}")


if __name__ == "__main__":
    main()