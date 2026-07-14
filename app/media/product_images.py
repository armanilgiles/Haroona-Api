from __future__ import annotations

import hashlib
import io
import ipaddress
import os
import socket
from dataclasses import dataclass
from urllib.parse import quote, urlparse

import boto3
import requests
from PIL import Image, ImageOps
from botocore.config import Config


MAX_SOURCE_BYTES = 15 * 1024 * 1024
DEFAULT_MAX_WIDTH = 640
DEFAULT_MAX_HEIGHT = 960
DEFAULT_QUALITY = 72


class ProductImageOptimizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class OptimizedProductImage:
    url: str
    width: int
    height: int
    key: str
    byte_count: int


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ProductImageOptimizationError(
            f"{name} is required for product image optimization"
        )
    return value


def _validate_public_https_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ProductImageOptimizationError("Product image URL must use HTTPS")

    try:
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)
        }
    except socket.gaierror as exc:
        raise ProductImageOptimizationError(
            f"Could not resolve image host: {parsed.hostname}"
        ) from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ProductImageOptimizationError(
                "Product image host resolved to a non-public address"
            )


def _download_image(url: str) -> bytes:
    current_url = url
    response = None

    for _ in range(4):
        _validate_public_https_url(current_url)
        response = requests.get(
            current_url,
            headers={
                "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                "User-Agent": "HaroonaMediaBot/1.0 (+https://www.haroona.com)",
            },
            timeout=(5, 25),
            stream=True,
            allow_redirects=False,
        )

        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise ProductImageOptimizationError(
                    "Image redirect did not include a destination"
                )
            current_url = requests.compat.urljoin(current_url, location)
            continue

        break
    else:
        raise ProductImageOptimizationError("Image URL redirected too many times")

    if response is None:
        raise ProductImageOptimizationError("Image request failed")

    response.raise_for_status()

    content_type = response.headers.get("content-type", "").lower()
    if content_type and not content_type.startswith("image/"):
        raise ProductImageOptimizationError(
            f"Source returned non-image content type: {content_type}"
        )

    content_length = response.headers.get("content-length")
    if content_length and int(content_length) > MAX_SOURCE_BYTES:
        raise ProductImageOptimizationError("Source image is larger than 15 MB")

    output = io.BytesIO()
    for chunk in response.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        output.write(chunk)
        if output.tell() > MAX_SOURCE_BYTES:
            raise ProductImageOptimizationError("Source image is larger than 15 MB")

    return output.getvalue()


def _encode_webp(
    source: bytes,
    *,
    max_width: int,
    max_height: int,
    quality: int,
) -> tuple[bytes, int, int]:
    try:
        with Image.open(io.BytesIO(source)) as opened:
            image = ImageOps.exif_transpose(opened)

            if getattr(image, "is_animated", False):
                image.seek(0)

            if image.mode not in {"RGB", "RGBA"}:
                image = image.convert("RGBA" if "A" in image.getbands() else "RGB")

            image.thumbnail(
                (max_width, max_height),
                resample=Image.Resampling.LANCZOS,
            )

            if image.mode == "RGBA":
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            output = io.BytesIO()
            image.save(
                output,
                format="WEBP",
                quality=quality,
                method=6,
                optimize=True,
            )
            return output.getvalue(), image.width, image.height
    except Exception as exc:
        raise ProductImageOptimizationError("Could not decode source image") from exc


def _build_s3_client():
    endpoint_url = os.getenv("HAROONA_MEDIA_ENDPOINT_URL", "").strip() or None
    region = os.getenv("HAROONA_MEDIA_REGION", "us-east-1").strip() or "us-east-1"

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=os.getenv("HAROONA_MEDIA_ACCESS_KEY_ID") or None,
        aws_secret_access_key=os.getenv("HAROONA_MEDIA_SECRET_ACCESS_KEY") or None,
        config=Config(signature_version="s3v4"),
    )


def optimize_and_upload_product_image(
    *,
    product_id: int,
    source_url: str,
    max_width: int = DEFAULT_MAX_WIDTH,
    max_height: int = DEFAULT_MAX_HEIGHT,
    quality: int = DEFAULT_QUALITY,
) -> OptimizedProductImage:
    if not 320 <= max_width <= 1600:
        raise ProductImageOptimizationError("max_width must be between 320 and 1600")
    if not 320 <= max_height <= 2400:
        raise ProductImageOptimizationError("max_height must be between 320 and 2400")
    if not 40 <= quality <= 90:
        raise ProductImageOptimizationError("quality must be between 40 and 90")

    bucket = _require_env("HAROONA_MEDIA_BUCKET")
    public_base_url = _require_env("HAROONA_MEDIA_PUBLIC_BASE_URL").rstrip("/")

    source_bytes = _download_image(source_url)
    optimized_bytes, width, height = _encode_webp(
        source_bytes,
        max_width=max_width,
        max_height=max_height,
        quality=quality,
    )

    fingerprint = hashlib.sha256(
        f"{source_url}|{max_width}|{max_height}|{quality}".encode("utf-8")
    ).hexdigest()[:16]
    key = f"products/{product_id}/{fingerprint}-{width}x{height}.webp"

    client = _build_s3_client()
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=optimized_bytes,
        ContentType="image/webp",
        CacheControl="public, max-age=31536000, immutable",
    )

    encoded_key = "/".join(quote(part, safe="") for part in key.split("/"))
    return OptimizedProductImage(
        url=f"{public_base_url}/{encoded_key}",
        width=width,
        height=height,
        key=key,
        byte_count=len(optimized_bytes),
    )
