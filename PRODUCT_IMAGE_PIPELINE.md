# Product image optimization

Haroona can keep the original merchant image URL for attribution/fallback while
serving a smaller WebP thumbnail from an S3-compatible object store.

## 1. Apply the database migration

```powershell
python -m alembic upgrade head
```

## 2. Configure object storage

The optimizer works with Amazon S3 and S3-compatible services such as
Cloudflare R2.

```text
HAROONA_MEDIA_BUCKET=
HAROONA_MEDIA_PUBLIC_BASE_URL=
HAROONA_MEDIA_ENDPOINT_URL=
HAROONA_MEDIA_REGION=auto
HAROONA_MEDIA_ACCESS_KEY_ID=
HAROONA_MEDIA_SECRET_ACCESS_KEY=
```

For Amazon S3, `HAROONA_MEDIA_ENDPOINT_URL` can be omitted. The public base URL
must be the CDN/public URL for the bucket, without a trailing slash.

Only rehost or transform assets when the merchant or affiliate program permits
it. The original merchant URL remains stored in `product_image_url`.

## 3. Optimize a small batch first

```powershell
python -m app.scripts.optimize_product_images --limit 10
```

Then inspect the feed and the live site. Continue in controlled batches:

```powershell
python -m app.scripts.optimize_product_images --limit 100
```

Rebuild a specific product:

```powershell
python -m app.scripts.optimize_product_images --product-id 123 --force
```

The API prefers `optimized_product_image_url` and includes the original image as
a fallback. Existing products continue to work before they are migrated.
