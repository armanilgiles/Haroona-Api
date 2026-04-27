from __future__ import annotations
import csv
from app.catalog.manual_seed_registry import SEED_LIST

with open("manual_links.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f)
    writer.writerow(["seed", "brand", "city", "product_name", "affiliate_url", "merchant_url"])
    for seed in SEED_LIST:
        for item in seed.products:
            writer.writerow([
                seed.key,
                seed.brand_name,
                seed.city_name,
                item["name"],
                item["affiliate_url"],
                item["merchant_url"],
            ])
