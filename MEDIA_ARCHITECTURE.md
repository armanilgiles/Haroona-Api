# Haroona media architecture

Product images remain backward compatible: the database keeps the original
merchant URL and may also hold an optimized object-storage URL. The shared
storage boundary now lives in `app/media/storage.py`; image processing is only
one consumer of it.

## Voice-reaction implementation path

Batch 2 implements this request flow:

1. The browser sends MIME type, byte size, and intended review/product owner.
2. FastAPI validates authentication, ownership, type, duration/size policy, and
   creates a pending media record plus a short-lived signed upload URL.
3. The browser uploads directly to object storage with the required headers.
4. The browser confirms completion; FastAPI verifies the object size, MIME type,
   reaction ID, and approved duration metadata before making it playable.
5. A background worker handles duration/waveform extraction, compression,
   moderation, and optional transcription.
6. Object storage or a CDN serves playback with byte-range support. FastAPI
   returns metadata and authorization URLs, not audio bytes.

Do not accept large audio bodies through a normal FastAPI request, store audio
blobs in PostgreSQL, or proxy routine playback through the API.

## Voice-reaction persistence foundation

Batch 1 adds `voice_reactions` for community state and `media_assets` for the
uploaded object's technical metadata. Audio bytes remain in object storage;
PostgreSQL stores only references and metadata. Product deletion cascades
through the reaction and its media row, while user/city deletion clears optional
attribution without destroying the reaction.

The persistence contract includes:

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

`app/media/audio.py` centralizes the browser audio MIME allowlist, recording
limits, MIME normalization, and opaque collision-resistant key generation.

## Batch 2 API boundary

- `GET /products/{product_id}/voice-reactions` returns paginated metadata only.
- `POST /products/{product_id}/voice-reactions/upload-init` requires login,
  validates the audio policy, generates the storage key, and returns a signed
  PUT handoff.
- `POST /voice-reactions/{reaction_id}/upload-complete` is owner-only and does
  not publish the reaction until object metadata is verified.
- `GET /voice-reactions/{reaction_id}/playback` returns a short-lived private
  playback URL only for published, ready media.
- `DELETE /voice-reactions/{reaction_id}` is owner-only and immediately hides
  the database record before best-effort object cleanup.

The API never accepts a client-selected storage key and never returns storage
keys in public metadata. Existing `HAROONA_MEDIA_*` settings are reused; Batch 2
adds no environment variables.

## Batch 5 launch and moderation operations

- Signed browser uploads require the object-storage bucket CORS policy to allow
  `PUT` from the production Haroona web origins. Allow the signed
  `Content-Type` and `x-amz-meta-*` request headers; do not make the bucket
  public.
- Configure the existing `ADMIN_EMAILS` setting in production. Production
  moderation endpoints fail closed when no admin allowlist is configured.
- Schedule `python -m app.scripts.cleanup_voice_reactions` periodically (for
  example, hourly). It expires abandoned pending rows before attempting
  best-effort object deletion. Upload initialization also cleans stale pending
  uploads for the current user.
- Community reports never automatically hide a reaction. An allowlisted admin
  reviews the private queue and explicitly hides, restores, or dismisses it.
- Report submission, upload creation, and unfinished uploads are database-rate
  limited. These limits work across serverless instances without adding Redis.

Batch 5 adds no new environment variables.

## Product-detail loading rule

Voice-reaction list responses contain metadata only. Render each audio element
with `preload="none"`, initialize the player on interaction, and request a
playback URL only when needed. Never download all recordings during the initial
product-detail render.

The existing product-detail endpoint remains unchanged. Voice reactions are
always fetched independently so product-detail query performance is isolated.
