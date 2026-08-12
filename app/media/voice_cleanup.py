from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, joinedload

from app.media.storage import (
    MediaStorageConfigurationError,
    MediaStorageOperationError,
    delete_media_object,
)
from app.models import VoiceReaction


logger = logging.getLogger(__name__)

DEFAULT_PENDING_UPLOAD_TTL = timedelta(hours=1)


@dataclass(frozen=True)
class VoiceCleanupResult:
    expired: int
    objects_deleted: int
    object_delete_failures: int


def cleanup_stale_voice_uploads(
    db: Session,
    *,
    user_id: str | None = None,
    older_than: timedelta = DEFAULT_PENDING_UPLOAD_TTL,
    limit: int = 100,
) -> VoiceCleanupResult:
    if older_than.total_seconds() <= 0:
        raise ValueError("older_than must be positive")
    if not 1 <= limit <= 1000:
        raise ValueError("limit must be between 1 and 1000")

    query = (
        db.query(VoiceReaction)
        .options(joinedload(VoiceReaction.media_asset))
        .filter(
            VoiceReaction.status == "pending",
            VoiceReaction.created_at < datetime.now(UTC) - older_than,
        )
    )
    if user_id is not None:
        query = query.filter(VoiceReaction.user_id == user_id)

    stale = query.order_by(VoiceReaction.created_at.asc()).limit(limit).all()
    storage_keys: list[str] = []
    for reaction in stale:
        reaction.status = "deleted"
        if reaction.media_asset is not None:
            reaction.media_asset.status = "deleted"
            storage_keys.append(reaction.media_asset.storage_key)

    if stale:
        db.commit()

    objects_deleted = 0
    failures = 0
    for storage_key in storage_keys:
        try:
            delete_media_object(storage_key=storage_key)
            objects_deleted += 1
        except (MediaStorageConfigurationError, MediaStorageOperationError):
            failures += 1
            logger.warning(
                "voice_reaction_stale_object_cleanup_failed storage_key=%s",
                storage_key,
            )

    return VoiceCleanupResult(
        expired=len(stale),
        objects_deleted=objects_deleted,
        object_delete_failures=failures,
    )
