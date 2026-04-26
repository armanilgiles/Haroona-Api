from __future__ import annotations

import argparse

from app.catalog.manual_product_service import seed_manual_products
from app.catalog.manual_seed_registry import SEEDS, get_manual_seed


def print_available_seeds() -> None:
    print("Available manual product seeds:")
    for key, seed in SEEDS.items():
        print(f"- {key}: {seed.brand_name} / {seed.city_name} / {len(seed.products)} products")


def run_seed(seed_key: str) -> None:
    seed = get_manual_seed(seed_key)
    created_or_updated = seed_manual_products(seed)

    print(f"Added/updated {len(created_or_updated)} products for {seed.brand_name} / {seed.city_name}:")
    for name in created_or_updated:
        print(f"- {name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed manually curated Haroona products.")
    parser.add_argument(
        "seed",
        nargs="?",
        default="all",
        help="Seed key to run, or 'all'. Example: rainbow_nyc",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available manual product seeds.",
    )

    args = parser.parse_args()

    if args.list:
        print_available_seeds()
        return

    if args.seed == "all":
        for seed_key in SEEDS:
            run_seed(seed_key)
        return

    run_seed(args.seed)


if __name__ == "__main__":
    main()
