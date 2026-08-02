# Published product refresh

This workflow checks live, published `products` against their original merchant
pages and, when present, checks the affiliate URL separately.

Dry run is the default. Phase 2 never deletes, archives, deactivates, or
automatically unpublishes a product.

## Database migration

```bash
alembic upgrade head
```

The migration adds product/link check timestamps, the last refresh result,
consecutive failure tracking, and a manual-review flag. Existing price snapshot
rows continue to record confirmed old/new prices.

## Commands

```bash
# Safest default: a 20-product dry-run sample
python -m app.scripts.refresh_published_products

# One known database product
python -m app.scripts.refresh_published_products --dry-run --product-id <id>

# Rainbow Shops known product(s)
python -m app.scripts.refresh_published_products \
  --dry-run \
  --merchant "Rainbow Shops"

# Controlled pilot sample
python -m app.scripts.refresh_published_products --dry-run --limit 20

# Every currently published product, without database changes
python -m app.scripts.refresh_published_products \
  --dry-run \
  --all \
  --output product-refresh-report.json

# Apply safe changes to a controlled sample
python -m app.scripts.refresh_published_products --apply --limit 20

# Apply safe changes to one reviewed product
python -m app.scripts.refresh_published_products --apply --product-id <id>
```

A full-catalog apply is intentionally disabled in this phase. Use a selector
after reviewing the dry-run report.

## Status behavior

- `price_changed` updates only when the page contains verified product data,
  identity confidence is high, and currency is consistent.
- `product_unavailable`, `likely_unavailable`, `affiliate_link_broken`, and
  `parse_failure` are flagged for manual review.
- `blocked_or_unknown` and `temporary_failure` record uncertainty but never
  imply that the product is gone.
- An affiliate-link failure never marks the original product unavailable.
