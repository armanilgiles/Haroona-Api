from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


class MediaStorageConfigurationError(RuntimeError):
    pass


class MediaStorageOperationError(RuntimeError):
    pass


class MediaObjectNotFoundError(MediaStorageOperationError):
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


@dataclass(frozen=True)
class SignedMediaDownload:
    url: str
    expires_in_seconds: int


@dataclass(frozen=True)
class MediaObjectMetadata:
    content_length: int
    content_type: str
    metadata: dict[str, str]


def validate_media_storage_key(storage_key: str) -> str:
    """Validate an application-generated relative object-storage key."""

    if not isinstance(storage_key, str) or not storage_key:
        raise ValueError("storage_key must be a safe relative object key")
    if len(storage_key) > 1024 or storage_key.startswith("/"):
        raise ValueError("storage_key must be a safe relative object key")
    if "\\" in storage_key or any(ord(character) < 32 for character in storage_key):
        raise ValueError("storage_key must be a safe relative object key")

    segments = storage_key.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise ValueError("storage_key must be a safe relative object key")
    return storage_key


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
    validated_key = validate_media_storage_key(storage_key)
    encoded_key = "/".join(quote(part, safe="") for part in validated_key.split("/"))
    return f"{settings.public_base_url}/{encoded_key}"


def create_signed_media_upload(
    *,
    storage_key: str,
    mime_type: str,
    metadata: Mapping[str, str] | None = None,
    expires_in_seconds: int = 900,
) -> SignedMediaUpload:
    """Create the storage handoff used by future direct browser uploads."""

    validated_key = validate_media_storage_key(storage_key)
    if not mime_type or "/" not in mime_type:
        raise ValueError("mime_type must be a valid media MIME type")
    if not 60 <= expires_in_seconds <= 3600:
        raise ValueError("expires_in_seconds must be between 60 and 3600")

    normalized_metadata: dict[str, str] = {}
    for key, value in (metadata or {}).items():
        normalized_key = key.strip().lower()
        normalized_value = value.strip()
        if not normalized_key or not normalized_value:
            raise ValueError("media metadata keys and values must not be empty")
        if not normalized_key.replace("-", "").isalnum():
            raise ValueError("media metadata keys must be alphanumeric or hyphenated")
        normalized_metadata[normalized_key] = normalized_value

    settings = get_media_storage_settings()
    params: dict[str, object] = {
        "Bucket": settings.bucket,
        "Key": validated_key,
        "ContentType": mime_type,
    }
    if normalized_metadata:
        params["Metadata"] = normalized_metadata

    try:
        client = build_media_storage_client(settings)
        url = client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=expires_in_seconds,
        )
    except (BotoCoreError, ClientError) as exc:
        raise MediaStorageOperationError("could not create signed upload") from exc

    headers = {"Content-Type": mime_type}
    headers.update(
        {
            f"x-amz-meta-{key}": value
            for key, value in normalized_metadata.items()
        }
    )
    return SignedMediaUpload(
        url=url,
        storage_key=validated_key,
        method="PUT",
        headers=headers,
        expires_in_seconds=expires_in_seconds,
    )


def get_media_object_metadata(*, storage_key: str) -> MediaObjectMetadata:
    validated_key = validate_media_storage_key(storage_key)
    settings = get_media_storage_settings()
    try:
        client = build_media_storage_client(settings)
        response = client.head_object(Bucket=settings.bucket, Key=validated_key)
    except ClientError as exc:
        error_code = str(exc.response.get("Error", {}).get("Code", ""))
        if error_code in {"404", "NoSuchKey", "NotFound"}:
            raise MediaObjectNotFoundError("media object was not found") from exc
        raise MediaStorageOperationError("could not inspect media object") from exc
    except BotoCoreError as exc:
        raise MediaStorageOperationError("could not inspect media object") from exc

    return MediaObjectMetadata(
        content_length=int(response.get("ContentLength", 0)),
        content_type=str(response.get("ContentType", "")),
        metadata={
            str(key).lower(): str(value)
            for key, value in dict(response.get("Metadata") or {}).items()
        },
    )


def create_signed_media_download(
    *,
    storage_key: str,
    mime_type: str,
    expires_in_seconds: int = 300,
) -> SignedMediaDownload:
    validated_key = validate_media_storage_key(storage_key)
    if not mime_type or "/" not in mime_type:
        raise ValueError("mime_type must be a valid media MIME type")
    if not 60 <= expires_in_seconds <= 3600:
        raise ValueError("expires_in_seconds must be between 60 and 3600")

    settings = get_media_storage_settings()
    try:
        client = build_media_storage_client(settings)
        url = client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": settings.bucket,
                "Key": validated_key,
                "ResponseContentType": mime_type,
            },
            ExpiresIn=expires_in_seconds,
        )
    except (BotoCoreError, ClientError) as exc:
        raise MediaStorageOperationError("could not create signed playback URL") from exc

    return SignedMediaDownload(url=url, expires_in_seconds=expires_in_seconds)


def delete_media_object(*, storage_key: str) -> None:
    validated_key = validate_media_storage_key(storage_key)
    settings = get_media_storage_settings()
    try:
        client = build_media_storage_client(settings)
        client.delete_object(Bucket=settings.bucket, Key=validated_key)
    except (BotoCoreError, ClientError) as exc:
        raise MediaStorageOperationError("could not delete media object") from exc
