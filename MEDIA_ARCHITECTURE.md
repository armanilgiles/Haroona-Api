# Haroona media architecture

Product images remain backward compatible: the database keeps the original
merchant URL and may also hold an optimized object-storage URL. The shared
storage boundary now lives in `app/media/storage.py`; image processing is only
one consumer of it.

## Voice-review implementation path

When voice reviews are built, use this request flow:

1. The browser sends MIME type, byte size, and intended review/product owner.
2. FastAPI validates authentication, ownership, type, duration/size policy, and
   creates a pending media record plus a short-lived signed upload URL.
3. The browser uploads directly to object storage with the required headers.
4. The browser confirms completion; FastAPI verifies object metadata and marks
   the record uploaded.
5. A background worker handles duration/waveform extraction, compression,
   moderation, and optional transcription.
6. Object storage or a CDN serves playback with byte-range support. FastAPI
   returns metadata and authorization URLs, not audio bytes.

Do not accept large audio bodies through a normal FastAPI request, store audio
blobs in PostgreSQL, or proxy routine playback through the API.

## Persistence contract for the voice-review phase

Add the media table alongside the review model so it can use real foreign keys.
The minimum useful metadata is:

- owner/review and product relationship
- media type and MIME type
- opaque storage key (never a local filesystem path)
- public/private delivery policy
- duration and byte size
- processing status
- optional waveform reference
- transcription status/reference
- moderation status/reference
- creation/update timestamps

Store derived artifacts under separate keys. Keep storage keys stable and use
versioned or content-addressed keys so CDN responses can be immutable.

## Product-detail loading rule

Future voice-review list responses should contain metadata only. Render each
audio element with `preload="none"`, initialize the player on interaction, and
request a playback URL only when needed. Never download all recordings during
the initial product-detail render.

`create_signed_media_upload()` is deliberately not exposed as a public API yet.
The future endpoint must add authentication, ownership, quotas, MIME allowlists,
and storage-key generation before calling it.
