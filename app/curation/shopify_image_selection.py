from __future__ import annotations

import io
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

try:
    import requests
except ImportError:  # pragma: no cover - requests is required by the API runtime
    requests = None

try:
    from PIL import Image, ImageStat
except ImportError:  # pragma: no cover - image scoring gracefully falls back to metadata
    Image = None
    ImageStat = None


IMAGE_MODE_FAST = "fast"
IMAGE_MODE_SMART = "smart"
IMAGE_MODE_MODEL_ONLY = "model_only"
SUPPORTED_IMAGE_MODES = {IMAGE_MODE_FAST, IMAGE_MODE_SMART, IMAGE_MODE_MODEL_ONLY}
MAX_IMAGE_CANDIDATES_PER_PRODUCT = 8
MAX_SMART_PREVIEWS_PER_PRODUCT = 3
MAX_IMAGE_PREVIEW_BYTES = 1_200_000
MODEL_WORN_SCORE_THRESHOLD = 42


@dataclass(frozen=True)
class ShopifyImageCandidate:
    url: str
    alt: str | None = None
    width: int | None = None
    height: int | None = None
    position: int = 0


@dataclass(frozen=True)
class ShopifyImageSelection:
    url: str | None
    score: int | None
    candidates_checked: int


@dataclass
class ShopifyImageSelectionCache:
    image_loads: dict[str, bool] = field(default_factory=dict)
    image_previews: dict[str, bytes | None] = field(default_factory=dict)


def normalize_image_mode(image_mode: str | None) -> str:
    normalized = (image_mode or IMAGE_MODE_SMART).strip().lower().replace("-", "_")
    if normalized in {"model", "strict", "strict_model"}:
        return IMAGE_MODE_MODEL_ONLY
    if normalized not in SUPPORTED_IMAGE_MODES:
        return IMAGE_MODE_SMART
    return normalized


def image_candidates_from_shopify_product(
    product: dict[str, Any],
) -> list[ShopifyImageCandidate]:
    raw_images = product.get("images")
    if not isinstance(raw_images, list):
        raw_images = []

    primary_image = product.get("image")
    if isinstance(primary_image, dict):
        raw_images = [primary_image, *raw_images]

    candidates: list[ShopifyImageCandidate] = []
    seen: set[str] = set()

    for index, image in enumerate(raw_images):
        if not isinstance(image, dict):
            continue

        url = str(image.get("src") or image.get("url") or "").strip()
        parsed = urlparse(url)
        if not url or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        if url in seen:
            continue

        seen.add(url)
        candidates.append(
            ShopifyImageCandidate(
                url=url,
                alt=str(image.get("alt") or "").strip() or None,
                width=_positive_int(image.get("width")),
                height=_positive_int(image.get("height")),
                position=_positive_int(image.get("position")) or index + 1,
            )
        )

        if len(candidates) >= MAX_IMAGE_CANDIDATES_PER_PRODUCT:
            break

    return candidates


def select_shopify_product_image(
    candidates: list[ShopifyImageCandidate],
    *,
    image_mode: str,
    referer: str,
    timeout_seconds: int = 6,
    cache: ShopifyImageSelectionCache | None = None,
) -> ShopifyImageSelection:
    mode = normalize_image_mode(image_mode)
    if not candidates:
        return ShopifyImageSelection(url=None, score=None, candidates_checked=0)

    if mode == IMAGE_MODE_FAST:
        checked = 0
        for candidate in candidates:
            checked += 1
            if _cached_image_url_loads(
                candidate.url,
                referer=referer,
                timeout_seconds=timeout_seconds,
                cache=cache,
            ):
                return ShopifyImageSelection(
                    url=candidate.url,
                    score=None,
                    candidates_checked=checked,
                )
        return ShopifyImageSelection(url=None, score=None, candidates_checked=checked)

    ranked_candidates = sorted(
        candidates,
        key=_candidate_metadata_score,
        reverse=True,
    )[:MAX_SMART_PREVIEWS_PER_PRODUCT]

    best_url: str | None = None
    best_score: int | None = None
    checked = 0
    for candidate in ranked_candidates:
        checked += 1
        preview = _cached_download_image_preview(
            candidate.url,
            referer=referer,
            timeout_seconds=timeout_seconds,
            cache=cache,
        )
        if preview is None:
            continue

        score = _score_likely_model_worn_image(preview) + _candidate_metadata_score(candidate)
        if best_score is None or score > best_score:
            best_url = candidate.url
            best_score = score

    if best_url is None:
        return ShopifyImageSelection(url=None, score=None, candidates_checked=checked)
    if mode == IMAGE_MODE_MODEL_ONLY and (best_score or 0) < MODEL_WORN_SCORE_THRESHOLD:
        return ShopifyImageSelection(
            url=None,
            score=best_score,
            candidates_checked=checked,
        )
    return ShopifyImageSelection(
        url=best_url,
        score=best_score,
        candidates_checked=checked,
    )


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _candidate_metadata_score(candidate: ShopifyImageCandidate) -> int:
    text = f"{candidate.url} {candidate.alt or ''}".lower()
    score = 0

    if candidate.width and candidate.height:
        portrait_ratio = candidate.height / candidate.width
        if portrait_ratio >= 1.15:
            score += 7
        elif portrait_ratio < 0.85:
            score -= 4

    if any(
        token in text
        for token in ("model", "lookbook", "lifestyle", "worn", "wear", "outfit", "campaign")
    ):
        score += 12
    if any(
        token in text
        for token in ("flat", "packshot", "swatch", "colorchip", "detail", "closeup", "thumbnail")
    ):
        score -= 14

    score -= min(max(candidate.position - 1, 0), 5)
    return score


def _response_has_image_content(response: Any) -> bool:
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


def _request_timeout(timeout_seconds: int) -> float:
    return min(max(float(timeout_seconds or 3), 1.5), 4.0)


def _image_headers(referer: str) -> dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (compatible; HaroonaCurator/0.1; +https://haroona.com)",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Referer": referer,
    }


def _image_url_loads(
    image_url: str,
    *,
    referer: str,
    timeout_seconds: int,
) -> bool:
    if requests is None:
        return False

    timeout = _request_timeout(timeout_seconds)
    headers = _image_headers(referer)

    try:
        head_response = requests.head(
            image_url,
            headers=headers,
            allow_redirects=True,
            timeout=timeout,
        )
        if _response_has_image_content(head_response):
            return True
        if head_response.status_code >= 400 and head_response.status_code not in {403, 405, 406}:
            return False
    except requests.RequestException:
        pass

    try:
        get_headers = {**headers, "Range": "bytes=0-2047"}
        with requests.get(
            image_url,
            headers=get_headers,
            stream=True,
            timeout=timeout,
        ) as response:
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


def _download_image_preview(
    image_url: str,
    *,
    referer: str,
    timeout_seconds: int,
) -> bytes | None:
    if requests is None:
        return None

    timeout = _request_timeout(timeout_seconds)
    headers = {
        **_image_headers(referer),
        "Range": f"bytes=0-{MAX_IMAGE_PREVIEW_BYTES - 1}",
    }

    try:
        with requests.get(
            image_url,
            headers=headers,
            stream=True,
            timeout=timeout,
        ) as response:
            if response.status_code >= 400:
                return None

            chunks = bytearray()
            for chunk in response.iter_content(chunk_size=16_384):
                if not chunk:
                    continue
                chunks.extend(chunk)
                if len(chunks) >= MAX_IMAGE_PREVIEW_BYTES:
                    break

            preview = bytes(chunks)
            if not preview:
                return None
            if _response_has_image_content(response) or _bytes_look_like_image(preview[:64]):
                return preview
    except requests.RequestException:
        return None
    return None


def _cached_image_url_loads(
    image_url: str,
    *,
    referer: str,
    timeout_seconds: int,
    cache: ShopifyImageSelectionCache | None,
) -> bool:
    if cache is None:
        return _image_url_loads(
            image_url,
            referer=referer,
            timeout_seconds=timeout_seconds,
        )

    cached = cache.image_loads.get(image_url)
    if cached is not None:
        return cached

    loaded = _image_url_loads(
        image_url,
        referer=referer,
        timeout_seconds=timeout_seconds,
    )
    cache.image_loads[image_url] = loaded
    return loaded


def _cached_download_image_preview(
    image_url: str,
    *,
    referer: str,
    timeout_seconds: int,
    cache: ShopifyImageSelectionCache | None,
) -> bytes | None:
    if cache is None:
        return _download_image_preview(
            image_url,
            referer=referer,
            timeout_seconds=timeout_seconds,
        )
    if image_url in cache.image_previews:
        return cache.image_previews[image_url]

    preview = _download_image_preview(
        image_url,
        referer=referer,
        timeout_seconds=timeout_seconds,
    )
    cache.image_previews[image_url] = preview
    if preview is not None:
        cache.image_loads[image_url] = True
    return preview


def _score_likely_model_worn_image(image_bytes: bytes) -> int:
    if Image is None or ImageStat is None:
        return 0

    try:
        with Image.open(io.BytesIO(image_bytes)) as opened:
            image = opened.convert("RGB")
            width, height = image.size
            if not width or not height:
                return 0

            image.thumbnail((96, 96))
            sample_width, sample_height = image.size
            pixels = list(image.getdata())
            if not pixels:
                return 0

            border = (
                [image.getpixel((x, 0)) for x in range(sample_width)]
                + [image.getpixel((x, sample_height - 1)) for x in range(sample_width)]
                + [image.getpixel((0, y)) for y in range(sample_height)]
                + [image.getpixel((sample_width - 1, y)) for y in range(sample_height)]
            )
            border_average = tuple(
                sum(pixel[channel] for pixel in border) / len(border)
                for channel in range(3)
            )

            def distance_from_border(pixel: tuple[int, int, int]) -> float:
                return sum(
                    abs(pixel[channel] - border_average[channel])
                    for channel in range(3)
                ) / 3

            foreground_ratio = sum(
                1 for pixel in pixels if distance_from_border(pixel) > 34
            ) / len(pixels)
            color_stddev = sum(ImageStat.Stat(image).stddev) / 3
            portrait_ratio = height / width

            score = 0
            if portrait_ratio >= 1.15:
                score += 6
            if 0.30 <= foreground_ratio < 0.45:
                score += 12
            elif foreground_ratio >= 0.45:
                score += 28
            if 26 <= color_stddev < 42:
                score += 12
            elif color_stddev >= 42:
                score += 28
            if foreground_ratio >= 0.42 and color_stddev >= 34:
                score += 24
            if foreground_ratio < 0.22 and color_stddev < 30:
                score -= 22
            return int(score)
    except Exception:
        return 0
