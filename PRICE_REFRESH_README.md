# Haroona daily price refresh

This patch separates product seeding from product freshness.

## What changed

- Adds product-level refresh metadata:
  - `regular_price`
  - `availability_status`
  - `last_price_checked_at`
  - `price_check_status`
  - `price_check_error`
- Adds `product_price_snapshots` so price/availability changes are auditable.
- Fixes `normalize_awin_raw.py` so newer feed imports update the existing normalized row instead of colliding with the unique `(external_product_id, source)` constraint.
- Fixes `promote_awin_normalized.py` where it referenced an undefined `item` variable while updating products.
- Adds `python -m app.scripts.refresh_product_prices`.

## First-time setup

Run the migration:

```bash
alembic upgrade head
```

## Daily flow for Awin CSV feeds

After downloading/exporting the latest Awin product CSV:

```bash
python -m app.scripts.import_awin_csv /path/to/latest-awin-feed.csv
python -m app.scripts.normalize_awin_raw
python -m app.scripts.refresh_product_prices --source awin
```

## Safe test run

```bash
python -m app.scripts.refresh_product_prices --source awin --dry-run
```

## Keep out-of-stock products visible

By default, the refresh deactivates products when the feed says they are not in stock.
To avoid that:

```bash
python -m app.scripts.refresh_product_prices --source awin --keep-out-of-stock-active
```

## What this does not do

This does not scrape merchant product pages. It refreshes from your normalized affiliate/feed rows. That is the safer MVP path.
