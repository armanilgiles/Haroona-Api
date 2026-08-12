from __future__ import annotations

import hashlib
from uuid import UUID, uuid4


ALLOWED_AUDIO_MIME_TYPES = frozenset(
    {
        "audio/mp4",
        "audio/mpeg",
        "audio/ogg",
        "audio/webm",
    }
)

AUDIO_FILE_EXTENSION_BY_MIME_TYPE = {
    "audio/mp4": "m4a",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/webm": "webm",
}

# The upload-init endpoint enforces these limits and the capabilities endpoint
# exposes them to recording clients so the browser and API stay in sync.
MAX_VOICE_RECORDING_DURATION_SECONDS = 90
MAX_VOICE_RECORDING_FILE_SIZE_BYTES = 10 * 1024 * 1024


def normalize_audio_mime_type(mime_type: str) -> str:
    """Return the canonical MIME type used in persistence and storage metadata."""

    normalized = mime_type.partition(";")[0].strip().lower()
    if normalized not in ALLOWED_AUDIO_MIME_TYPES:
        raise ValueError("unsupported audio MIME type")
    return normalized


def generate_voice_storage_key(
    *,
    user_id: str,
    mime_type: str,
    unique_id: UUID | None = None,
) -> str:
    """Build an opaque, collision-resistant key without using a client path."""

    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise ValueError("user_id is required")

    canonical_mime_type = normalize_audio_mime_type(mime_type)
    extension = AUDIO_FILE_EXTENSION_BY_MIME_TYPE[canonical_mime_type]
    user_segment = hashlib.sha256(normalized_user_id.encode("utf-8")).hexdigest()[:24]
    object_id = unique_id or uuid4()
    return f"voice/{user_segment}/{object_id.hex}.{extension}"
