import json
from app.catalog.manual_seed_registry import SEED_LIST

out = []
for seed in SEED_LIST:
    for item in seed.products:
        out.append({
            "seed": seed.key,
            "brand": seed.brand_name,
            "city": seed.city_name,
            "product_name": item["name"],
            "affiliate_url": item["affiliate_url"],
            "merchant_url": item["merchant_url"],
        })

with open("manual_links.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
