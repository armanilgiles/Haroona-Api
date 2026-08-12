from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.auth.dependencies import get_admin_user, get_current_user
from app.database import get_db
from app.media.audio import (
    ALLOWED_AUDIO_MIME_TYPES,
    MAX_VOICE_RECORDING_DURATION_SECONDS,
    MAX_VOICE_RECORDING_FILE_SIZE_BYTES,
    generate_voice_storage_key,
    normalize_audio_mime_type,
)
from app.media.voice_cleanup import cleanup_stale_voice_uploads
from app.media.storage import (
    MediaObjectNotFoundError,
    MediaStorageConfigurationError,
    MediaStorageOperationError,
    create_signed_media_download,
    create_signed_media_upload,
    delete_media_object,
    get_media_object_metadata,
)
from app.models import (
    City,
    MediaAsset,
    Product,
    User,
    VoiceReaction,
    VoiceReactionReport,
)
from app.schemas import (
    SignedMediaUploadOut,
    VoiceReactionCapabilitiesOut,
    VoiceReactionCreatorOut,
    VoiceReactionListOut,
    VoiceReactionModerationIn,
    VoiceReactionModerationItemOut,
    VoiceReactionModerationListOut,
    VoiceReactionModerationReportOut,
    VoiceReactionOut,
    VoiceReactionPlaybackOut,
    VoiceReactionUploadCompleteOut,
    VoiceReactionUploadInitIn,
    VoiceReactionUploadInitOut,
    VoiceReactionReportIn,
    VoiceReactionReportOut,
)


logger = logging.getLogger(__name__)

router = APIRouter(tags=["voice-reactions"])

UPLOAD_URL_EXPIRES_IN_SECONDS = 900
PLAYBACK_URL_EXPIRES_IN_SECONDS = 300
MAX_PENDING_UPLOADS_PER_PRODUCT_AND_USER = 3
MAX_PENDING_UPLOADS_PER_USER = 10
MAX_PUBLISHED_REACTIONS_PER_USER_PER_HOUR = 5
MAX_REPORTS_PER_USER_PER_DAY = 20


def _error(*, status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _serialize_reaction(reaction: VoiceReaction) -> VoiceReactionOut:
    media_asset = reaction.media_asset
    if media_asset is None:
        raise RuntimeError("voice reaction is missing media metadata")

    creator = None
    if reaction.user is not None:
        creator = VoiceReactionCreatorOut(
            id=reaction.user.id,
            name=reaction.user.name,
            avatar=reaction.user.avatar,
        )

    return VoiceReactionOut(
        id=reaction.id,
        productId=reaction.product_id,
        reactionTag=reaction.reaction_tag,
        experienceType=reaction.experience_type,
        complimentResponse=reaction.compliment_response,
        cityId=reaction.city_id,
        citySlug=reaction.city.slug if reaction.city else None,
        cityName=reaction.city.name if reaction.city else None,
        creator=creator,
        mimeType=media_asset.mime_type,
        fileSizeBytes=int(media_asset.file_size_bytes or 0),
        durationMs=int(media_asset.duration_ms or 0),
        createdAt=reaction.created_at,
    )


def _reaction_with_media(db: Session, reaction_id: int) -> VoiceReaction | None:
    return (
        db.query(VoiceReaction)
        .options(
            joinedload(VoiceReaction.user),
            joinedload(VoiceReaction.city),
            joinedload(VoiceReaction.media_asset),
        )
        .filter(VoiceReaction.id == reaction_id)
        .first()
    )


def _require_owner(reaction: VoiceReaction, user: User) -> None:
    if reaction.user_id != user.id:
        raise _error(
            status_code=status.HTTP_403_FORBIDDEN,
            code="voice_reaction_forbidden",
            message="You do not own this voice reaction.",
        )


def _mark_verification_failed(
    db: Session,
    reaction: VoiceReaction,
    media_asset: MediaAsset,
) -> None:
    reaction.status = "hidden"
    media_asset.status = "failed"
    db.commit()


@router.get(
    "/voice-reactions/capabilities",
    response_model=VoiceReactionCapabilitiesOut,
)
def get_voice_reaction_capabilities(
    response: Response,
) -> VoiceReactionCapabilitiesOut:
    response.headers["Cache-Control"] = "public, max-age=3600"
    return VoiceReactionCapabilitiesOut(
        allowedMimeTypes=sorted(ALLOWED_AUDIO_MIME_TYPES),
        maxDurationMs=MAX_VOICE_RECORDING_DURATION_SECONDS * 1000,
        maxFileSizeBytes=MAX_VOICE_RECORDING_FILE_SIZE_BYTES,
    )


@router.get(
    "/products/{product_id}/voice-reactions",
    response_model=VoiceReactionListOut,
)
def get_product_voice_reactions(
    product_id: int,
    limit: int = Query(10, ge=1, le=20),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> VoiceReactionListOut:
    rows = (
        db.query(VoiceReaction)
        .join(VoiceReaction.media_asset)
        .options(
            joinedload(VoiceReaction.user),
            joinedload(VoiceReaction.city),
            joinedload(VoiceReaction.media_asset),
        )
        .filter(
            VoiceReaction.product_id == product_id,
            VoiceReaction.status == "published",
            MediaAsset.status == "ready",
        )
        .order_by(VoiceReaction.created_at.desc(), VoiceReaction.id.desc())
        .offset(offset)
        .limit(limit + 1)
        .all()
    )

    has_more = len(rows) > limit
    items = rows[:limit]
    return VoiceReactionListOut(
        items=[_serialize_reaction(reaction) for reaction in items],
        limit=limit,
        offset=offset,
        nextOffset=offset + limit if has_more else None,
        hasMore=has_more,
    )


@router.post(
    "/voice-reactions/{reaction_id}/reports",
    response_model=VoiceReactionReportOut,
    status_code=status.HTTP_201_CREATED,
)
def report_voice_reaction(
    reaction_id: int,
    payload: VoiceReactionReportIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VoiceReactionReportOut:
    reaction = _reaction_with_media(db, reaction_id)
    if (
        reaction is None
        or reaction.status != "published"
        or reaction.media_asset is None
        or reaction.media_asset.status != "ready"
    ):
        raise _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="voice_reaction_not_found",
            message="This voice reaction is not available.",
        )
    if reaction.user_id == user.id:
        raise _error(
            status_code=status.HTTP_409_CONFLICT,
            code="voice_reaction_report_own",
            message="You can delete your own reaction instead of reporting it.",
        )

    recent_report_count = (
        db.query(VoiceReactionReport.id)
        .filter(
            VoiceReactionReport.reporter_user_id == user.id,
            VoiceReactionReport.created_at >= datetime.now(UTC) - timedelta(days=1),
        )
        .count()
    )
    if recent_report_count >= MAX_REPORTS_PER_USER_PER_DAY:
        raise _error(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="voice_reaction_report_limit",
            message="You’ve reached the report limit. Please try again later.",
        )

    report = VoiceReactionReport(
        voice_reaction_id=reaction.id,
        reporter_user_id=user.id,
        reason=payload.reason,
        details=payload.details,
        status="open",
    )
    db.add(report)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise _error(
            status_code=status.HTTP_409_CONFLICT,
            code="voice_reaction_already_reported",
            message="You’ve already reported this voice reaction.",
        )
    db.refresh(report)
    return VoiceReactionReportOut(
        id=report.id,
        reactionId=report.voice_reaction_id,
        reason=report.reason,
        status=report.status,
        createdAt=report.created_at,
    )


def _serialize_moderation_item(
    reaction: VoiceReaction,
) -> VoiceReactionModerationItemOut:
    open_reports = [report for report in reaction.reports if report.status == "open"]
    reports = sorted(
        reaction.reports,
        key=lambda report: (report.created_at, report.id),
        reverse=True,
    )
    return VoiceReactionModerationItemOut(
        reaction=_serialize_reaction(reaction),
        productName=reaction.product.name,
        reactionStatus=reaction.status,
        openReportCount=len(open_reports),
        reports=[
            VoiceReactionModerationReportOut(
                id=report.id,
                reason=report.reason,
                details=report.details,
                status=report.status,
                reporterName=report.reporter.name if report.reporter else None,
                createdAt=report.created_at,
            )
            for report in reports
        ],
    )


@router.get(
    "/admin/voice-reactions",
    response_model=VoiceReactionModerationListOut,
)
def get_voice_reaction_moderation_queue(
    queue: Literal["reported", "hidden", "published", "all"] = Query("reported"),
    limit: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
    _admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> VoiceReactionModerationListOut:
    query = (
        db.query(VoiceReaction)
        .join(VoiceReaction.media_asset)
        .options(
            joinedload(VoiceReaction.product),
            joinedload(VoiceReaction.user),
            joinedload(VoiceReaction.city),
            joinedload(VoiceReaction.media_asset),
            selectinload(VoiceReaction.reports).joinedload(
                VoiceReactionReport.reporter
            ),
        )
        .filter(VoiceReaction.status != "deleted")
    )
    if queue == "reported":
        query = query.filter(
            VoiceReaction.reports.any(VoiceReactionReport.status == "open")
        )
    elif queue == "hidden":
        query = query.filter(VoiceReaction.status == "hidden")
    elif queue == "published":
        query = query.filter(VoiceReaction.status == "published")

    rows = (
        query.order_by(VoiceReaction.updated_at.desc(), VoiceReaction.id.desc())
        .offset(offset)
        .limit(limit + 1)
        .all()
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    return VoiceReactionModerationListOut(
        items=[_serialize_moderation_item(reaction) for reaction in items],
        limit=limit,
        offset=offset,
        nextOffset=offset + limit if has_more else None,
        hasMore=has_more,
    )


@router.patch(
    "/admin/voice-reactions/{reaction_id}/moderation",
    response_model=VoiceReactionModerationItemOut,
)
def moderate_voice_reaction(
    reaction_id: int,
    payload: VoiceReactionModerationIn,
    admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> VoiceReactionModerationItemOut:
    reaction = (
        db.query(VoiceReaction)
        .options(
            joinedload(VoiceReaction.product),
            joinedload(VoiceReaction.user),
            joinedload(VoiceReaction.city),
            joinedload(VoiceReaction.media_asset),
            selectinload(VoiceReaction.reports).joinedload(
                VoiceReactionReport.reporter
            ),
        )
        .filter(VoiceReaction.id == reaction_id)
        .first()
    )
    if reaction is None or reaction.status == "deleted":
        raise _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="voice_reaction_not_found",
            message="This voice reaction could not be found.",
        )

    now = datetime.now(UTC)
    open_reports = [report for report in reaction.reports if report.status == "open"]
    if payload.action == "hide":
        reaction.status = "hidden"
        for report in open_reports:
            report.status = "resolved"
            report.resolved_by_user_id = admin.id
            report.resolved_at = now
    elif payload.action == "restore":
        if reaction.media_asset is None or reaction.media_asset.status != "ready":
            raise _error(
                status_code=status.HTTP_409_CONFLICT,
                code="voice_reaction_media_not_ready",
                message="This voice reaction cannot be restored until its media is ready.",
            )
        reaction.status = "published"
    else:
        for report in open_reports:
            report.status = "dismissed"
            report.resolved_by_user_id = admin.id
            report.resolved_at = now

    db.commit()
    return _serialize_moderation_item(reaction)


@router.get(
    "/admin/voice-reactions/{reaction_id}/playback",
    response_model=VoiceReactionPlaybackOut,
)
def get_admin_voice_reaction_playback(
    reaction_id: int,
    response: Response,
    _admin: User = Depends(get_admin_user),
    db: Session = Depends(get_db),
) -> VoiceReactionPlaybackOut:
    reaction = _reaction_with_media(db, reaction_id)
    if (
        reaction is None
        or reaction.status == "deleted"
        or reaction.media_asset is None
        or reaction.media_asset.status != "ready"
    ):
        raise _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="voice_reaction_not_found",
            message="This voice reaction is not available.",
        )
    try:
        playback = create_signed_media_download(
            storage_key=reaction.media_asset.storage_key,
            mime_type=reaction.media_asset.mime_type,
            expires_in_seconds=PLAYBACK_URL_EXPIRES_IN_SECONDS,
        )
    except (MediaStorageConfigurationError, MediaStorageOperationError):
        raise _error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="media_storage_unavailable",
            message="Voice playback is temporarily unavailable.",
        )
    response.headers["Cache-Control"] = "private, no-store"
    return VoiceReactionPlaybackOut(
        url=playback.url,
        expiresInSeconds=playback.expires_in_seconds,
    )


@router.post(
    "/products/{product_id}/voice-reactions/upload-init",
    response_model=VoiceReactionUploadInitOut,
    status_code=status.HTTP_201_CREATED,
)
def initialize_voice_reaction_upload(
    product_id: int,
    payload: VoiceReactionUploadInitIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VoiceReactionUploadInitOut:
    cleanup_stale_voice_uploads(db, user_id=user.id)

    product = db.query(Product).filter(Product.id == product_id).first()
    if product is None:
        raise _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="product_not_found",
            message="This Haroona product could not be found.",
        )
    if not product.is_active:
        raise _error(
            status_code=status.HTTP_410_GONE,
            code="product_unavailable",
            message="This product is no longer available.",
        )

    if payload.cityId is not None:
        city_exists = (
            db.query(City.id).filter(City.id == payload.cityId).scalar() is not None
        )
        if not city_exists:
            raise _error(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                code="voice_reaction_city_invalid",
                message="The selected city could not be found.",
            )

    existing_rows = (
        db.query(VoiceReaction.status)
        .filter(
            VoiceReaction.product_id == product_id,
            VoiceReaction.user_id == user.id,
            VoiceReaction.status.in_(["pending", "published"]),
        )
        .all()
    )
    if any(row.status == "published" for row in existing_rows):
        raise _error(
            status_code=status.HTTP_409_CONFLICT,
            code="voice_reaction_already_exists",
            message="You already have a voice reaction for this product.",
        )
    if len(existing_rows) >= MAX_PENDING_UPLOADS_PER_PRODUCT_AND_USER:
        raise _error(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="voice_reaction_upload_limit",
            message="Too many unfinished uploads exist for this product.",
        )

    pending_count = (
        db.query(VoiceReaction.id)
        .filter(
            VoiceReaction.user_id == user.id,
            VoiceReaction.status == "pending",
        )
        .count()
    )
    if pending_count >= MAX_PENDING_UPLOADS_PER_USER:
        raise _error(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="voice_reaction_pending_limit",
            message="Too many unfinished voice uploads exist. Please try again later.",
        )

    recent_published_count = (
        db.query(VoiceReaction.id)
        .filter(
            VoiceReaction.user_id == user.id,
            VoiceReaction.status == "published",
            VoiceReaction.created_at >= datetime.now(UTC) - timedelta(hours=1),
        )
        .count()
    )
    if recent_published_count >= MAX_PUBLISHED_REACTIONS_PER_USER_PER_HOUR:
        raise _error(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="voice_reaction_rate_limit",
            message="You’ve reached the voice reaction limit. Please try again later.",
        )

    reaction = VoiceReaction(
        product_id=product_id,
        user_id=user.id,
        city_id=payload.cityId,
        reaction_tag="general",
        experience_type=payload.experienceType,
        compliment_response=payload.complimentResponse,
        status="pending",
    )
    media_asset = MediaAsset(
        storage_key=generate_voice_storage_key(
            user_id=user.id,
            mime_type=payload.mimeType,
        ),
        mime_type=payload.mimeType,
        file_size_bytes=payload.fileSizeBytes,
        duration_ms=payload.durationMs,
        status="pending",
    )
    reaction.media_asset = media_asset
    db.add(reaction)

    try:
        db.flush()
        upload = create_signed_media_upload(
            storage_key=media_asset.storage_key,
            mime_type=media_asset.mime_type,
            metadata={
                "voice-reaction-id": str(reaction.id),
                "duration-ms": str(media_asset.duration_ms),
            },
            expires_in_seconds=UPLOAD_URL_EXPIRES_IN_SECONDS,
        )
        reaction_id = reaction.id
        db.commit()
    except (MediaStorageConfigurationError, MediaStorageOperationError):
        db.rollback()
        raise _error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="media_storage_unavailable",
            message="Voice upload storage is temporarily unavailable.",
        )

    return VoiceReactionUploadInitOut(
        reactionId=reaction_id,
        upload=SignedMediaUploadOut(
            url=upload.url,
            method="PUT",
            headers=upload.headers,
            expiresInSeconds=upload.expires_in_seconds,
        ),
    )


@router.post(
    "/voice-reactions/{reaction_id}/upload-complete",
    response_model=VoiceReactionUploadCompleteOut,
)
def complete_voice_reaction_upload(
    reaction_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VoiceReactionUploadCompleteOut:
    reaction = _reaction_with_media(db, reaction_id)
    if reaction is None or reaction.status == "deleted":
        raise _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="voice_reaction_not_found",
            message="This voice reaction could not be found.",
        )
    _require_owner(reaction, user)

    media_asset = reaction.media_asset
    if media_asset is None:
        raise _error(
            status_code=status.HTTP_409_CONFLICT,
            code="voice_reaction_media_missing",
            message="This voice reaction has no media upload.",
        )
    if reaction.status == "published" and media_asset.status == "ready":
        return VoiceReactionUploadCompleteOut(
            reaction=_serialize_reaction(reaction)
        )
    if reaction.status != "pending" or media_asset.status not in {"pending", "uploaded"}:
        raise _error(
            status_code=status.HTTP_409_CONFLICT,
            code="voice_reaction_upload_not_pending",
            message="This voice upload can no longer be completed.",
        )

    try:
        object_metadata = get_media_object_metadata(
            storage_key=media_asset.storage_key
        )
    except MediaObjectNotFoundError:
        raise _error(
            status_code=status.HTTP_409_CONFLICT,
            code="voice_reaction_upload_missing",
            message="The audio upload has not finished yet.",
        )
    except (MediaStorageConfigurationError, MediaStorageOperationError):
        raise _error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="media_storage_unavailable",
            message="Voice upload storage is temporarily unavailable.",
        )

    try:
        uploaded_mime_type = normalize_audio_mime_type(object_metadata.content_type)
    except ValueError:
        uploaded_mime_type = ""

    metadata_matches = (
        object_metadata.content_length == media_asset.file_size_bytes
        and 0 < object_metadata.content_length <= MAX_VOICE_RECORDING_FILE_SIZE_BYTES
        and uploaded_mime_type == media_asset.mime_type
        and object_metadata.metadata.get("voice-reaction-id") == str(reaction.id)
        and object_metadata.metadata.get("duration-ms")
        == str(media_asset.duration_ms)
    )
    if not metadata_matches:
        _mark_verification_failed(db, reaction, media_asset)
        raise _error(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="voice_reaction_upload_invalid",
            message="The uploaded audio did not match the approved upload.",
        )

    media_asset.file_size_bytes = object_metadata.content_length
    media_asset.mime_type = uploaded_mime_type
    media_asset.status = "ready"
    reaction.status = "published"
    serialized_reaction = _serialize_reaction(reaction)
    db.commit()

    return VoiceReactionUploadCompleteOut(
        reaction=serialized_reaction
    )


@router.get(
    "/voice-reactions/{reaction_id}/playback",
    response_model=VoiceReactionPlaybackOut,
)
def get_voice_reaction_playback(
    reaction_id: int,
    response: Response,
    db: Session = Depends(get_db),
) -> VoiceReactionPlaybackOut:
    reaction = _reaction_with_media(db, reaction_id)
    if (
        reaction is None
        or reaction.status != "published"
        or reaction.media_asset is None
        or reaction.media_asset.status != "ready"
    ):
        raise _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="voice_reaction_not_found",
            message="This voice reaction is not available.",
        )

    try:
        playback = create_signed_media_download(
            storage_key=reaction.media_asset.storage_key,
            mime_type=reaction.media_asset.mime_type,
            expires_in_seconds=PLAYBACK_URL_EXPIRES_IN_SECONDS,
        )
    except (MediaStorageConfigurationError, MediaStorageOperationError):
        raise _error(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="media_storage_unavailable",
            message="Voice playback is temporarily unavailable.",
        )

    response.headers["Cache-Control"] = "private, no-store"
    return VoiceReactionPlaybackOut(
        url=playback.url,
        expiresInSeconds=playback.expires_in_seconds,
    )


@router.delete(
    "/voice-reactions/{reaction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_voice_reaction(
    reaction_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    reaction = _reaction_with_media(db, reaction_id)
    if reaction is None or reaction.status == "deleted":
        raise _error(
            status_code=status.HTTP_404_NOT_FOUND,
            code="voice_reaction_not_found",
            message="This voice reaction could not be found.",
        )
    _require_owner(reaction, user)

    storage_key = reaction.media_asset.storage_key if reaction.media_asset else None
    reaction.status = "deleted"
    if reaction.media_asset is not None:
        reaction.media_asset.status = "deleted"
    db.commit()

    if storage_key:
        try:
            delete_media_object(storage_key=storage_key)
        except (
            MediaStorageConfigurationError,
            MediaStorageOperationError,
        ):
            logger.warning(
                "voice_reaction_object_cleanup_failed reaction_id=%s",
                reaction_id,
            )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
