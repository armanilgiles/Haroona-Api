from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote

import boto3
from botocore.config import Config


class MediaStorageConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class MediaStorageSettings:
    bucket: str
    public_base_url: str | None
    endpoint_url: str | None
    region: str
    access_key_id: str | None
    secret_access_key: str | None


@dataclass(frozen=True)
class SignedMediaUpload:
    url: str
    storage_key: str
    method: str
    headers: dict[str, str]
    expires_in_seconds: int


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise MediaStorageConfigurationError(f"{name} is required")
    return value


def get_media_storage_settings(
    *,
    require_public_base_url: bool = False,
) -> MediaStorageSettings:
    public_base_url = os.getenv("HAROONA_MEDIA_PUBLIC_BASE_URL", "").strip()
    if require_public_base_url and not public_base_url:
        raise MediaStorageConfigurationError(
            "HAROONA_MEDIA_PUBLIC_BASE_URL is required"
        )

    return MediaStorageSettings(
        bucket=_required_env("HAROONA_MEDIA_BUCKET"),
        public_base_url=public_base_url.rstrip("/") or None,
        endpoint_url=os.getenv("HAROONA_MEDIA_ENDPOINT_URL", "").strip() or None,
        region=os.getenv("HAROONA_MEDIA_REGION", "us-east-1").strip()
        or "us-east-1",
        access_key_id=os.getenv("HAROONA_MEDIA_ACCESS_KEY_ID") or None,
        secret_access_key=os.getenv("HAROONA_MEDIA_SECRET_ACCESS_KEY") or None,
    )


def build_media_storage_client(settings: MediaStorageSettings):
    return boto3.client(
        "s3",
        endpoint_url=settings.endpoint_url,
        region_name=settings.region,
        aws_access_key_id=settings.access_key_id,
        aws_secret_access_key=settings.secret_access_key,
        config=Config(signature_version="s3v4"),
    )


def build_public_media_url(
    settings: MediaStorageSettings,
    storage_key: str,
) -> str:
    if not settings.public_base_url:
        raise MediaStorageConfigurationError(
            "HAROONA_MEDIA_PUBLIC_BASE_URL is required"
        )
    encoded_key = "/".join(quote(part, safe="") for part in storage_key.split("/"))
    return f"{settings.public_base_url}/{encoded_key}"


def create_signed_media_upload(
    *,
    storage_key: str,
    mime_type: str,
    expires_in_seconds: int = 900,
) -> SignedMediaUpload:
    """Create the storage handoff used by future direct browser uploads."""

    if not storage_key or storage_key.startswith("/") or ".." in storage_key.split("/"):
        raise ValueError("storage_key must be a safe relative object key")
    if not mime_type or "/" not in mime_type:
        raise ValueError("mime_type must be a valid media MIME type")
    if not 60 <= expires_in_seconds <= 3600:
        raise ValueError("expires_in_seconds must be between 60 and 3600")

    settings = get_media_storage_settings()
    client = build_media_storage_client(settings)
    url = client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.bucket,
            "Key": storage_key,
            "ContentType": mime_type,
        },
        ExpiresIn=expires_in_seconds,
    )
    return SignedMediaUpload(
        url=url,
        storage_key=storage_key,
        method="PUT",
        headers={"Content-Type": mime_type},
        expires_in_seconds=expires_in_seconds,
    )
