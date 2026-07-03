from __future__ import annotations

import base64
import json
import re
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse, urlunparse

import requests
from sqlalchemy.orm import Session

from app.curation.scoring import score_city_fit
from app.curation.shopify_collection import (
    USER_AGENT,
    CandidatePayload,
    CollectionScanOptions,
    _normalize_category,
    _parse_decimal,
    _strip_html,
    upsert_product_candidates,
)


PRICE_PATTERN = re.compile(r"\$\s*([0-9][0-9,]*(?:\.\d{2})?)")
CATEGORY_ID_PATTERN = re.compile(r"/category/[^/?#]*-cid-(\d+)", re.IGNORECASE)
COLLECTION_PATTERN = re.compile(r"/collection/[^/?#]+/?$", re.IGNORECASE)
GOODS_ID_PATTERN = re.compile(r"(?:-|/)(\d{6,})(?:$|[/?#])")
SCRIPT_PATTERN = re.compile(r"<script[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)


class _ProductAnchorParser(HTMLParser):
    """Small stdlib-only parser for ShopCider's server-rendered category links."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._anchor_stack: list[dict[str, Any]] = []
        self.items: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {key.lower(): value or "" for key, value in attrs}

        if tag.lower() == "a":
            href = attr_map.get("href", "")
            if _looks_like_shopcider_product_url(href):
                self._anchor_stack.append(
                    {
                        "href": urljoin(self.base_url, href),
                        "text": [],
                        "image_url": None,
                    }
                )
            return

        if self._anchor_stack and tag.lower() in {"img", "source"}:
            src = _first_image_attribute(attr_map)
            if src and not self._anchor_stack[-1].get("image_url"):
                self._anchor_stack[-1]["image_url"] = _normalize_image_url(src, self.base_url)

    def handle_data(self, data: str) -> None:
        if self._anchor_stack:
            clean = re.sub(r"\s+", " ", data).strip()
            if clean:
                self._anchor_stack[-1]["text"].append(clean)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._anchor_stack:
            item = self._anchor_stack.pop()
            text = " ".join(item.pop("text", []))
            parsed = _candidate_from_anchor_text(
                href=item["href"],
                text=text,
                image_url=item.get("image_url"),
            )
            if parsed:
                self.items.append(parsed)


def _clean_source_url(source_url: str) -> str:
    parsed = urlparse(source_url.strip())
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def _is_shopcider_listing_url(source_url: str) -> bool:
    parsed = urlparse(source_url)
    host = parsed.netloc.lower()
    path = parsed.path
    return "shopcider.com" in host and (
        CATEGORY_ID_PATTERN.search(path) is not None or COLLECTION_PATTERN.search(path) is not None
    )


def _shopcider_listing_label(source_url: str) -> str:
    parsed = urlparse(source_url)
    category_match = CATEGORY_ID_PATTERN.search(parsed.path)
    if category_match:
        return f"category {category_match.group(1)}"

    collection_match = COLLECTION_PATTERN.search(parsed.path)
    if collection_match:
        return f"collection {parsed.path.rstrip('/').split('/')[-1]}"

    return parsed.path or source_url


def _looks_like_shopcider_product_url(href: str) -> bool:
    if not href:
        return False
    parsed = urlparse(href)
    return "/goods/" in parsed.path.lower() or "/product/" in parsed.path.lower()


def _first_image_attribute(attr_map: dict[str, str]) -> str | None:
    for key in (
        "src",
        "data-src",
        "data-original",
        "data-lazy",
        "data-lazy-src",
        "data-srcset",
        "srcset",
        "data-image",
        "data-url",
        "poster",
        "content",
    ):
        value = attr_map.get(key)
        if value and _looks_like_image_url(value):
            return value.split(",")[0].strip().split(" ")[0]
    return None


def _decode_business_tracking(raw_value: str | None) -> dict[str, Any] | None:
    if not raw_value:
        return None

    decoded_value = unquote(raw_value).strip()

    # Some ShopCider listing links leave raw + characters inside the
    # businessTracking query param. parse_qs treats + as a space, which breaks
    # normal base64 decoding and caused skcFirstImg to be missed. Convert those
    # spaces back before decoding.
    decoded_value = decoded_value.replace(" ", "+")
    padding = "=" * (-len(decoded_value) % 4)

    try:
        decoded_json = base64.b64decode(decoded_value + padding).decode("utf-8")
        payload = json.loads(decoded_json)
    except Exception:
        try:
            decoded_json = base64.urlsafe_b64decode(decoded_value + padding).decode("utf-8")
            payload = json.loads(decoded_json)
        except Exception:
            return None

    return payload if isinstance(payload, dict) else None


def _normalize_image_url(value: str | None, base_url: str) -> str | None:
    if not value:
        return None

    cleaned = value.strip().strip('"\'')
    if not cleaned:
        return None

    first_src = cleaned.split(",")[0].strip().split(" ")[0]
    if not _looks_like_image_url(first_src):
        return None

    if first_src.startswith("//"):
        return f"https:{first_src}"
    if first_src.startswith("http://") or first_src.startswith("https://"):
        return first_src
    if first_src.startswith("/"):
        return urljoin(base_url, first_src)

    # ShopCider listing links often hide the first image filename inside the
    # businessTracking query param as skcFirstImg. A bare filename needs the
    # ShopCider product image CDN prefix to render in Curate Studio.
    if re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:jpg|jpeg|png|webp)", first_src, re.IGNORECASE):
        return f"https://img1.shopcider.com/product/{first_src}"

    return urljoin(base_url, first_src)


def _image_from_tracking_query(merchant_url: str, base_url: str) -> str | None:
    parsed = urlparse(merchant_url)
    query = parse_qs(parsed.query)

    tracking = _decode_business_tracking(query.get("businessTracking", [None])[0])
    if not tracking:
        return None

    for key in ("skcFirstImg", "firstImage", "first_image", "image", "imageUrl", "image_url"):
        image_url = _normalize_image_url(str(tracking.get(key) or ""), base_url)
        if image_url:
            return image_url

    return None


SHOPCIDER_IMAGE_HOSTS = ("img1.shopcider.com", "img.shopcider.com", "img2.shopcider.com")


def _shopcider_image_url_candidates(image_url: str | None, base_url: str) -> list[str]:
    normalized = _normalize_image_url(image_url, base_url)
    if not normalized:
        return []

    candidates: list[str] = []

    def add(candidate: str) -> None:
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    add(normalized)

    parsed = urlparse(normalized)
    if parsed.scheme in {"http", "https"} and "shopcider.com" in parsed.netloc.lower():
        for host in SHOPCIDER_IMAGE_HOSTS:
            add(urlunparse((parsed.scheme, host, parsed.path, parsed.params, parsed.query, parsed.fragment)))
            add(urlunparse((parsed.scheme, host, parsed.path, parsed.params, "", parsed.fragment)))

    return candidates


def _response_has_image_content(response: requests.Response) -> bool:
    if response.status_code >= 400:
        return False

    content_type = response.headers.get("Content-Type", "").lower()
    return content_type.startswith("image/") or "image" in content_type


def _bytes_look_like_image(chunk: bytes) -> bool:
    return (
        chunk.startswith(b"\xff\xd8")
        or chunk.startswith(b"\x89PNG")
        or chunk.startswith(b"RIFF") and b"WEBP" in chunk[:16]
        or chunk.lstrip().startswith(b"<svg")
    )


def _image_url_loads(image_url: str, timeout_seconds: int = 6) -> bool:
    timeout = min(max(float(timeout_seconds or 3), 1.5), 4.0)
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": "https://www.shopcider.com/",
    }

    try:
        head_response = requests.head(image_url, headers=headers, allow_redirects=True, timeout=timeout)
        if _response_has_image_content(head_response):
            return True
        if head_response.status_code >= 400 and head_response.status_code not in {403, 405, 406}:
            return False
    except requests.RequestException:
        pass

    try:
        get_headers = {**headers, "Range": "bytes=0-2047"}
        with requests.get(image_url, headers=get_headers, stream=True, timeout=timeout) as response:
            if _response_has_image_content(response):
                return True
            if response.status_code >= 400:
                return False

            for chunk in response.iter_content(chunk_size=64):
                if chunk:
                    return _bytes_look_like_image(chunk)
    except requests.RequestException:
        return False

    return False


def _verified_shopcider_image_url(
    image_url: str | None,
    base_url: str,
    timeout_seconds: int = 6,
) -> str | None:
    for candidate in _shopcider_image_url_candidates(image_url, base_url):
        if _image_url_loads(candidate, timeout_seconds=timeout_seconds):
            return candidate
    return None


def _extract_external_product_id(merchant_url: str, fallback: str) -> str:
    parsed = urlparse(merchant_url)
    query = parse_qs(parsed.query)
    for key in ("p", "spu", "goods_id", "product_id"):
        value = query.get(key, [None])[0]
        if value:
            return str(value)

    match = GOODS_ID_PATTERN.search(parsed.path)
    if match:
        return match.group(1)

    return fallback


def _clean_product_url(merchant_url: str) -> str:
    parsed = urlparse(merchant_url)
    query = parse_qs(parsed.query)
    keep: dict[str, str] = {}
    for key in ("p", "style_id"):
        value = query.get(key, [None])[0]
        if value:
            keep[key] = value

    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",
            urlencode(keep),
            "",
        )
    )


def _candidate_from_anchor_text(
    *,
    href: str,
    text: str,
    image_url: str | None,
) -> dict[str, Any] | None:
    if not text:
        return None

    price_matches = PRICE_PATTERN.findall(text)
    if not price_matches:
        return None

    price_amount = _parse_decimal(price_matches[0])
    if price_amount is None:
        return None

    title = PRICE_PATTERN.sub(" ", text, count=10)
    title = re.sub(r"\bADD TO BAG\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"^-\d+%", " ", title)
    title = re.sub(r"\+\s*\d+\s*Colors?", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(Flash Shipping|Hot|Recycled|Sale)\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\s+", " ", title).strip(" -•|\t\n")

    if len(title) < 4:
        return None

    image_url = image_url or _image_from_tracking_query(href, href)
    clean_url = _clean_product_url(href)
    return {
        "external_product_id": _extract_external_product_id(clean_url, fallback=title.lower().replace(" ", "-")),
        "title": title,
        "description": None,
        "price_amount": price_amount,
        "currency": "USD",
        "merchant_url": clean_url,
        "image_url": image_url,
        "availability": "in_stock",
        "product_type": None,
        "tags": [],
        "brand_name": None,
    }


def _coerce_price(value: Any) -> Decimal | None:
    if isinstance(value, dict):
        for key in ("salePrice", "price", "amount", "value"):
            price = _coerce_price(value.get(key))
            if price is not None:
                return price
        return None

    if isinstance(value, (int, float)):
        # Some feeds use cents, some use dollars. ShopCider prices in this page
        # are usually dollars, but this guard keeps cents-shaped values readable.
        if value > 1000:
            return _parse_decimal(value / 100)
        return _parse_decimal(value)

    if isinstance(value, str):
        match = PRICE_PATTERN.search(value)
        if match:
            return _parse_decimal(match.group(1))
        return _parse_decimal(value)

    return None


def _first_string(record: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return None


def _image_from_record(record: dict[str, Any], base_url: str) -> str | None:
    direct = _first_string(
        record,
        (
            "image",
            "imageUrl",
            "image_url",
            "mainImage",
            "main_image",
            "firstImage",
            "first_image",
            "skcFirstImg",
            "skuFirstImg",
            "goodsImg",
            "goods_img",
            "goodsImage",
            "goods_image",
            "productImage",
            "product_image",
            "cover",
            "coverUrl",
            "cover_url",
            "pic",
            "picUrl",
            "pic_url",
            "url",
        ),
    )
    image_url = _normalize_image_url(direct, base_url)
    if image_url:
        return image_url

    for key in ("images", "imageList", "image_list", "gallery", "galleryImages", "skuList", "skus", "colorList"):
        value = record.get(key)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    image_url = _normalize_image_url(item, base_url)
                    if image_url:
                        return image_url
                if isinstance(item, dict):
                    image_url = _image_from_record(item, base_url)
                    if image_url:
                        return image_url

    return None


def _looks_like_image_url(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in (".jpg", ".jpeg", ".png", ".webp", "image", "img"))


def _url_from_record(record: dict[str, Any], base_url: str) -> str | None:
    direct = _first_string(
        record,
        ("url", "goodsUrl", "goods_url", "productUrl", "product_url", "link", "href"),
    )
    if direct and _looks_like_shopcider_product_url(direct):
        return _clean_product_url(urljoin(base_url, direct))

    slug = _first_string(record, ("slug", "seoUrl", "seo_url", "goodsNameUrl", "goods_name_url"))
    product_id = _first_string(record, ("goodsId", "goods_id", "spu", "spuId", "spu_id", "productId", "product_id", "id"))
    if slug and product_id:
        return _clean_product_url(urljoin(base_url, f"/goods/{slug}-{product_id}?p={product_id}"))

    return None


def _candidate_from_record(record: dict[str, Any], base_url: str) -> dict[str, Any] | None:
    title = _first_string(record, ("name", "title", "goodsName", "goods_name", "productName", "product_name"))
    merchant_url = _url_from_record(record, base_url)
    price_amount = None

    for key in (
        "salePrice",
        "sale_price",
        "price",
        "priceAmount",
        "price_amount",
        "minPrice",
        "min_price",
        "showPrice",
        "show_price",
    ):
        price_amount = _coerce_price(record.get(key))
        if price_amount is not None:
            break

    if not title or not merchant_url or price_amount is None:
        return None

    external_id = _first_string(
        record,
        ("goodsId", "goods_id", "spu", "spuId", "spu_id", "productId", "product_id", "id"),
    ) or _extract_external_product_id(merchant_url, fallback=title.lower().replace(" ", "-"))

    tags: list[str] = []
    for key in ("tags", "tagList", "labels", "labelList"):
        value = record.get(key)
        if isinstance(value, list):
            tags.extend(str(item.get("name") if isinstance(item, dict) else item) for item in value)

    description = _strip_html(_first_string(record, ("description", "desc", "subtitle")))
    product_type = _first_string(record, ("categoryName", "category_name", "type", "productType", "product_type"))

    image_url = _image_from_record(record, base_url) or _image_from_tracking_query(merchant_url, base_url)

    return {
        "external_product_id": str(external_id),
        "title": title,
        "description": description,
        "price_amount": price_amount,
        "currency": "USD",
        "merchant_url": merchant_url,
        "image_url": image_url,
        "availability": "in_stock",
        "product_type": product_type,
        "tags": [tag for tag in tags if tag and tag != "None"],
        "brand_name": _first_string(record, ("brandName", "brand_name", "brand")),
    }


def _walk_json(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    if isinstance(value, dict):
        if any(key in value for key in ("goodsId", "goods_id", "spu", "productId", "product_id")) and any(
            key in value for key in ("name", "title", "goodsName", "goods_name", "productName", "product_name")
        ):
            found.append(value)

        for child in value.values():
            found.extend(_walk_json(child))

    elif isinstance(value, list):
        for child in value:
            found.extend(_walk_json(child))

    return found


def _extract_json_script_objects(html: str) -> list[Any]:
    objects: list[Any] = []

    for match in SCRIPT_PATTERN.finditer(html):
        script = match.group(1).strip()
        if not script or "goods" not in script.lower():
            continue

        if script.startswith("{") or script.startswith("["):
            try:
                objects.append(json.loads(script))
                continue
            except json.JSONDecodeError:
                pass

        next_data_match = re.search(
            r"<script[^>]+id=[\"']__NEXT_DATA__[\"'][^>]*>(.*?)</script>",
            match.group(0),
            re.IGNORECASE | re.DOTALL,
        )
        if next_data_match:
            try:
                objects.append(json.loads(next_data_match.group(1)))
            except json.JSONDecodeError:
                pass

    return objects


def _extract_items_from_json(html: str, base_url: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()

    for obj in _extract_json_script_objects(html):
        for record in _walk_json(obj):
            item = _candidate_from_record(record, base_url)
            if not item:
                continue

            key = item["external_product_id"]
            if key in seen:
                continue
            seen.add(key)
            items.append(item)

    return items


def _extract_items_from_anchors(html: str, base_url: str) -> list[dict[str, Any]]:
    parser = _ProductAnchorParser(base_url)
    parser.feed(html)

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in parser.items:
        key = item["external_product_id"]
        if key in seen:
            continue
        seen.add(key)
        items.append(item)

    return items


def fetch_shopcider_category_products(options: CollectionScanOptions) -> list[dict[str, Any]]:
    source_url = _clean_source_url(options.source_url)
    if not _is_shopcider_listing_url(source_url):
        raise ValueError(
            "ShopCider URL must look like https://www.shopcider.com/category/{slug}-cid-{id} "
            "or https://www.shopcider.com/collection/{slug}"
        )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    response = requests.get(source_url, headers=headers, timeout=options.request_timeout_seconds)
    if response.status_code >= 400:
        raise RuntimeError(f"ShopCider category page returned HTTP {response.status_code}")

    html = response.text
    items = _extract_items_from_json(html, source_url)
    if not items:
        items = _extract_items_from_anchors(html, source_url)

    if not items:
        listing_label = _shopcider_listing_label(source_url)
        raise RuntimeError(
            f"Could not find product cards on ShopCider {listing_label}. "
            "The page markup may have changed or the listing may require browser rendering."
        )

    return items


def build_shopcider_candidate_payloads(options: CollectionScanOptions) -> list[CandidatePayload]:
    products = fetch_shopcider_category_products(options)
    payloads: list[CandidatePayload] = []
    clean_source_url = _clean_source_url(options.source_url)

    for product in products:
        title = str(product.get("title") or "").strip()
        external_id = str(product.get("external_product_id") or "").strip()
        if not title or not external_id:
            continue

        description = product.get("description")
        product_type = product.get("product_type")
        tags = product.get("tags") if isinstance(product.get("tags"), list) else []
        normalized_category = _normalize_category(title, product_type, options.normalized_category)

        score = score_city_fit(
            title=title,
            description=description,
            product_type=product_type,
            tags=tags,
            target_city_slug=options.target_city_slug,
            normalized_category=normalized_category,
            merchant_name=options.merchant_name,
        )

        image_url = _verified_shopcider_image_url(
            str(product.get("image_url") or ""),
            clean_source_url,
            timeout_seconds=options.request_timeout_seconds,
        )
        if not image_url:
            # Product imagery is required for the Curate Studio review queue.
            # If the CDN URL cannot be loaded server-side, skip the candidate
            # instead of saving a row that will render as a broken thumbnail.
            continue

        review_notes: list[str] = []
        if product.get("price_amount") is None:
            review_notes.append("missing price")
        if product.get("availability") != "in_stock":
            review_notes.append("not in stock")
        if not normalized_category:
            review_notes.append("unknown category")

        payloads.append(
            CandidatePayload(
                source="shopcider",
                source_type=options.source_type or "category",
                source_url=clean_source_url,
                merchant_name=options.merchant_name,
                brand_name=product.get("brand_name") or options.merchant_name,
                external_product_id=external_id,
                title=title,
                description=description,
                price_amount=product.get("price_amount"),
                currency=product.get("currency") or "USD",
                affiliate_url=None,
                merchant_url=product.get("merchant_url"),
                image_url=image_url,
                availability=product.get("availability") or "in_stock",
                normalized_category=normalized_category,
                target_city_slug=options.target_city_slug,
                city_connection_type=score.city_connection_type,
                city_connection_note=score.city_connection_note,
                haroona_score=score.score,
                score_reasons=score.reasons,
                review_notes="; ".join(review_notes) or None,
            )
        )

    payloads.sort(key=lambda item: item.haroona_score, reverse=True)
    return payloads[: options.limit]


def scan_and_save_shopcider_category(db: Session, options: CollectionScanOptions) -> dict[str, Any]:
    payloads = build_shopcider_candidate_payloads(options)
    counts = upsert_product_candidates(db, payloads)
    return {
        "status": "ok",
        "source_url": _clean_source_url(options.source_url),
        "merchant_name": options.merchant_name,
        "target_city_slug": options.target_city_slug,
        "found": len(payloads),
        **counts,
        "items": [
            {
                "external_product_id": item.external_product_id,
                "title": item.title,
                "price_amount": str(item.price_amount) if item.price_amount is not None else None,
                "currency": item.currency,
                "merchant_url": item.merchant_url,
                "image_url": item.image_url,
                "availability": item.availability,
                "normalized_category": item.normalized_category,
                "city_connection_type": item.city_connection_type,
                "city_connection_note": item.city_connection_note,
                "haroona_score": item.haroona_score,
                "score_reasons": item.score_reasons,
                "review_notes": item.review_notes,
            }
            for item in payloads
        ],
    }
