import unittest
from unittest.mock import patch

from fastapi import HTTPException, Response
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.media.storage import (
    MediaObjectMetadata,
    MediaStorageConfigurationError,
    SignedMediaDownload,
    SignedMediaUpload,
)
from app.models import (
    Brand,
    City,
    Country,
    MediaAsset,
    Product,
    User,
    VoiceReaction,
    VoiceReactionReport,
)
from app.routers.voice_reactions import (
    complete_voice_reaction_upload,
    delete_voice_reaction,
    get_voice_reaction_capabilities,
    get_product_voice_reactions,
    get_voice_reaction_moderation_queue,
    get_voice_reaction_playback,
    initialize_voice_reaction_upload,
    moderate_voice_reaction,
    report_voice_reaction,
)
from app.schemas import (
    VoiceReactionModerationIn,
    VoiceReactionReportIn,
    VoiceReactionUploadInitIn,
)


class VoiceReactionApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(dbapi_connection, _connection_record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        country = Country(code="US", name="United States")
        self.city = City(
            slug="new-york",
            name="New York",
            country=country,
            latitude=40.7128,
            longitude=-74.0060,
        )
        brand = Brand(name="Voice API Brand", country=country)
        self.user = User(
            id="voice-user-1",
            email="voice-user-1@example.test",
            name="Voice User",
        )
        self.other_user = User(
            id="voice-user-2",
            email="voice-user-2@example.test",
        )
        self.product = Product(
            external_id="voice-api-product",
            source="test",
            name="Voice API Product",
            currency="USD",
            brand=brand,
            city=self.city,
            is_active=True,
        )
        self.db.add_all(
            [country, self.city, brand, self.user, self.other_user, self.product]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _pending_reaction(
        self,
        *,
        user: User | None = None,
        storage_key: str = "voice/user/pending.webm",
    ) -> VoiceReaction:
        reaction = VoiceReaction(
            product_id=self.product.id,
            user_id=(user or self.user).id,
            city_id=self.city.id,
            reaction_tag="would_compliment",
            status="pending",
        )
        reaction.media_asset = MediaAsset(
            storage_key=storage_key,
            mime_type="audio/webm",
            file_size_bytes=4096,
            duration_ms=12_000,
            status="pending",
        )
        self.db.add(reaction)
        self.db.commit()
        return reaction

    def _published_reaction(
        self,
        *,
        user: User | None = None,
        storage_key: str = "voice/user/ready.webm",
    ) -> VoiceReaction:
        reaction = self._pending_reaction(user=user, storage_key=storage_key)
        reaction.status = "published"
        reaction.media_asset.status = "ready"
        self.db.commit()
        return reaction

    def test_capabilities_expose_the_limits_enforced_by_upload_init(self):
        response = Response()

        result = get_voice_reaction_capabilities(response)

        self.assertEqual(
            result.allowedMimeTypes,
            ["audio/mp4", "audio/mpeg", "audio/ogg", "audio/webm"],
        )
        self.assertEqual(result.maxDurationMs, 90_000)
        self.assertEqual(result.maxFileSizeBytes, 10 * 1024 * 1024)
        self.assertEqual(response.headers["Cache-Control"], "public, max-age=3600")

    def test_upload_init_creates_pending_rows_and_server_controlled_handoff(self):
        signed_upload = SignedMediaUpload(
            url="https://uploads.example.test/signed",
            storage_key="ignored-by-response",
            method="PUT",
            headers={
                "Content-Type": "audio/webm",
                "x-amz-meta-voice-reaction-id": "1",
                "x-amz-meta-duration-ms": "12000",
            },
            expires_in_seconds=900,
        )
        payload = VoiceReactionUploadInitIn(
            experienceType="first_impression",
            complimentResponse="yes",
            cityId=self.city.id,
            mimeType="audio/webm; codecs=opus",
            fileSizeBytes=4096,
            durationMs=12_000,
        )

        with patch(
            "app.routers.voice_reactions.create_signed_media_upload",
            return_value=signed_upload,
        ) as create_upload:
            result = initialize_voice_reaction_upload(
                self.product.id,
                payload,
                user=self.user,
                db=self.db,
            )

        reaction = self.db.get(VoiceReaction, result.reactionId)
        self.assertEqual(reaction.status, "pending")
        self.assertEqual(reaction.user_id, self.user.id)
        self.assertEqual(reaction.reaction_tag, "general")
        self.assertEqual(reaction.experience_type, "first_impression")
        self.assertEqual(reaction.compliment_response, "yes")
        self.assertEqual(reaction.media_asset.status, "pending")
        self.assertEqual(reaction.media_asset.mime_type, "audio/webm")
        self.assertEqual(reaction.media_asset.file_size_bytes, 4096)
        self.assertEqual(reaction.media_asset.duration_ms, 12_000)
        self.assertRegex(
            reaction.media_asset.storage_key,
            r"^voice/[a-f0-9]{24}/[a-f0-9]{32}\.webm$",
        )
        self.assertNotIn(self.user.id, reaction.media_asset.storage_key)
        self.assertEqual(result.upload.url, signed_upload.url)

        create_upload.assert_called_once_with(
            storage_key=reaction.media_asset.storage_key,
            mime_type="audio/webm",
            metadata={
                "voice-reaction-id": str(reaction.id),
                "duration-ms": "12000",
            },
            expires_in_seconds=900,
        )

    def test_upload_request_rejects_unsupported_or_oversized_audio(self):
        invalid_payloads = (
            {
                "experienceType": "first_impression",
                "mimeType": "audio/wav",
                "fileSizeBytes": 4096,
                "durationMs": 12_000,
            },
            {
                "experienceType": "first_impression",
                "mimeType": "audio/webm",
                "fileSizeBytes": 10 * 1024 * 1024 + 1,
                "durationMs": 12_000,
            },
            {
                "experienceType": "first_impression",
                "mimeType": "audio/webm",
                "fileSizeBytes": 4096,
                "durationMs": 90_001,
            },
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                VoiceReactionUploadInitIn(**payload)

    def test_experience_and_compliment_validation_matches_the_selected_signal(self):
        base_payload = {
            "mimeType": "audio/webm",
            "fileSizeBytes": 4096,
            "durationMs": 12_000,
        }

        first_impression = VoiceReactionUploadInitIn(
            experienceType="first_impression",
            complimentResponse="not_sure",
            **base_payload,
        )
        wore_it = VoiceReactionUploadInitIn(
            experienceType="wore_it",
            experienceConfirmed=True,
            **base_payload,
        )

        self.assertEqual(first_impression.complimentResponse, "not_sure")
        self.assertIsNone(wore_it.complimentResponse)

        invalid_payloads = (
            {
                "experienceType": "wore_it",
                "experienceConfirmed": True,
                "complimentResponse": "not_sure",
            },
            {
                "experienceType": "wore_it",
                "complimentResponse": "yes",
            },
            {
                "experienceType": "something_else",
            },
            {},
        )
        for values in invalid_payloads:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                VoiceReactionUploadInitIn(**values, **base_payload)

    def test_upload_init_rolls_back_when_storage_is_unavailable(self):
        payload = VoiceReactionUploadInitIn(
            experienceType="first_impression",
            mimeType="audio/webm",
            fileSizeBytes=4096,
            durationMs=12_000,
        )

        with patch(
            "app.routers.voice_reactions.create_signed_media_upload",
            side_effect=MediaStorageConfigurationError("bucket missing"),
        ), self.assertRaises(HTTPException) as raised:
            initialize_voice_reaction_upload(
                self.product.id,
                payload,
                user=self.user,
                db=self.db,
            )

        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(self.db.query(VoiceReaction).count(), 0)
        self.assertEqual(self.db.query(MediaAsset).count(), 0)

    def test_upload_init_rejects_a_second_published_reaction(self):
        self._published_reaction()
        payload = VoiceReactionUploadInitIn(
            experienceType="first_impression",
            mimeType="audio/webm",
            fileSizeBytes=4096,
            durationMs=12_000,
        )

        with patch(
            "app.routers.voice_reactions.create_signed_media_upload"
        ) as create_upload, self.assertRaises(HTTPException) as raised:
            initialize_voice_reaction_upload(
                self.product.id,
                payload,
                user=self.user,
                db=self.db,
            )

        self.assertEqual(raised.exception.status_code, 409)
        create_upload.assert_not_called()

    def test_completion_verifies_object_before_publishing(self):
        reaction = self._pending_reaction()
        reaction.reaction_tag = "general"
        reaction.experience_type = "first_impression"
        reaction.compliment_response = "no"
        self.db.commit()
        metadata = MediaObjectMetadata(
            content_length=4096,
            content_type="audio/webm",
            metadata={
                "voice-reaction-id": str(reaction.id),
                "duration-ms": "12000",
            },
        )

        with patch(
            "app.routers.voice_reactions.get_media_object_metadata",
            return_value=metadata,
        ) as head_object:
            result = complete_voice_reaction_upload(
                reaction.id,
                user=self.user,
                db=self.db,
            )

        self.db.refresh(reaction)
        self.db.refresh(reaction.media_asset)
        self.assertEqual(reaction.status, "published")
        self.assertEqual(reaction.media_asset.status, "ready")
        self.assertEqual(result.reaction.id, reaction.id)
        self.assertEqual(result.reaction.reactionTag, "general")
        self.assertEqual(result.reaction.experienceType, "first_impression")
        self.assertEqual(result.reaction.complimentResponse, "no")
        head_object.assert_called_once_with(
            storage_key=reaction.media_asset.storage_key
        )

    def test_completion_rejects_mismatched_object_and_hides_it(self):
        reaction = self._pending_reaction()
        metadata = MediaObjectMetadata(
            content_length=4097,
            content_type="audio/webm",
            metadata={
                "voice-reaction-id": str(reaction.id),
                "duration-ms": "12000",
            },
        )

        with patch(
            "app.routers.voice_reactions.get_media_object_metadata",
            return_value=metadata,
        ), self.assertRaises(HTTPException) as raised:
            complete_voice_reaction_upload(
                reaction.id,
                user=self.user,
                db=self.db,
            )

        self.assertEqual(raised.exception.status_code, 422)
        self.db.refresh(reaction)
        self.db.refresh(reaction.media_asset)
        self.assertEqual(reaction.status, "hidden")
        self.assertEqual(reaction.media_asset.status, "failed")

    def test_non_owner_cannot_complete_or_delete_reaction(self):
        reaction = self._pending_reaction()

        for action in (
            lambda: complete_voice_reaction_upload(
                reaction.id,
                user=self.other_user,
                db=self.db,
            ),
            lambda: delete_voice_reaction(
                reaction.id,
                user=self.other_user,
                db=self.db,
            ),
        ):
            with self.subTest(action=action), self.assertRaises(HTTPException) as raised:
                action()
            self.assertEqual(raised.exception.status_code, 403)

    def test_public_list_returns_only_published_ready_metadata_in_one_query(self):
        first = self._published_reaction(storage_key="voice/user/ready-1.webm")
        self._pending_reaction(storage_key="voice/user/pending-2.webm")
        product_id = self.product.id
        statements: list[str] = []

        def record_statement(_conn, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            result = get_product_voice_reactions(
                product_id,
                limit=10,
                offset=0,
                db=self.db,
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual([item.id for item in result.items], [first.id])
        self.assertEqual(len(statements), 1)
        serialized = result.model_dump()
        self.assertIsNone(result.items[0].experienceType)
        self.assertIsNone(result.items[0].complimentResponse)
        self.assertNotIn("storageKey", str(serialized))
        self.assertNotIn("playback", str(serialized).lower())

    def test_playback_is_on_demand_and_only_for_ready_reactions(self):
        ready = self._published_reaction()
        pending = self._pending_reaction(storage_key="voice/user/not-ready.webm")
        signed_download = SignedMediaDownload(
            url="https://media.example.test/signed-playback",
            expires_in_seconds=300,
        )
        response = Response()

        with patch(
            "app.routers.voice_reactions.create_signed_media_download",
            return_value=signed_download,
        ) as create_download:
            result = get_voice_reaction_playback(
                ready.id,
                response=response,
                db=self.db,
            )

        self.assertEqual(result.url, signed_download.url)
        self.assertEqual(response.headers["cache-control"], "private, no-store")
        create_download.assert_called_once_with(
            storage_key=ready.media_asset.storage_key,
            mime_type="audio/webm",
            expires_in_seconds=300,
        )

        with self.assertRaises(HTTPException) as raised:
            get_voice_reaction_playback(
                pending.id,
                response=Response(),
                db=self.db,
            )
        self.assertEqual(raised.exception.status_code, 404)

    def test_owner_delete_hides_reaction_before_best_effort_object_cleanup(self):
        reaction = self._published_reaction()
        storage_key = reaction.media_asset.storage_key

        with patch(
            "app.routers.voice_reactions.delete_media_object"
        ) as delete_object:
            response = delete_voice_reaction(
                reaction.id,
                user=self.user,
                db=self.db,
            )

        self.assertEqual(response.status_code, 204)
        self.db.refresh(reaction)
        self.db.refresh(reaction.media_asset)
        self.assertEqual(reaction.status, "deleted")
        self.assertEqual(reaction.media_asset.status, "deleted")
        delete_object.assert_called_once_with(storage_key=storage_key)

    def test_authenticated_member_can_report_a_published_reaction_once(self):
        reaction = self._published_reaction(user=self.other_user)

        result = report_voice_reaction(
            reaction.id,
            VoiceReactionReportIn(reason="spam", details="Repeated promotion"),
            user=self.user,
            db=self.db,
        )

        self.assertEqual(result.reactionId, reaction.id)
        self.assertEqual(result.status, "open")
        report = self.db.get(VoiceReactionReport, result.id)
        self.assertEqual(report.reporter_user_id, self.user.id)
        self.assertEqual(report.details, "Repeated promotion")

        with self.assertRaises(HTTPException) as raised:
            report_voice_reaction(
                reaction.id,
                VoiceReactionReportIn(reason="other"),
                user=self.user,
                db=self.db,
            )
        self.assertEqual(raised.exception.status_code, 409)

    def test_member_cannot_report_own_or_unpublished_reaction(self):
        own = self._published_reaction()
        pending = self._pending_reaction(
            user=self.other_user,
            storage_key="voice/user/unpublished-report.webm",
        )

        with self.assertRaises(HTTPException) as own_error:
            report_voice_reaction(
                own.id,
                VoiceReactionReportIn(reason="other"),
                user=self.user,
                db=self.db,
            )
        self.assertEqual(own_error.exception.status_code, 409)

        with self.assertRaises(HTTPException) as pending_error:
            report_voice_reaction(
                pending.id,
                VoiceReactionReportIn(reason="spam"),
                user=self.user,
                db=self.db,
            )
        self.assertEqual(pending_error.exception.status_code, 404)

    def test_admin_can_hide_and_restore_reported_reaction(self):
        reaction = self._published_reaction(user=self.other_user)
        report_voice_reaction(
            reaction.id,
            VoiceReactionReportIn(reason="harassment"),
            user=self.user,
            db=self.db,
        )

        queue = get_voice_reaction_moderation_queue(
            queue="reported",
            limit=20,
            offset=0,
            _admin=self.user,
            db=self.db,
        )
        self.assertEqual([item.reaction.id for item in queue.items], [reaction.id])
        self.assertEqual(queue.items[0].openReportCount, 1)

        hidden = moderate_voice_reaction(
            reaction.id,
            VoiceReactionModerationIn(action="hide"),
            admin=self.user,
            db=self.db,
        )
        self.assertEqual(hidden.reactionStatus, "hidden")
        self.assertEqual(hidden.openReportCount, 0)
        self.assertEqual(hidden.reports[0].status, "resolved")

        restored = moderate_voice_reaction(
            reaction.id,
            VoiceReactionModerationIn(action="restore"),
            admin=self.user,
            db=self.db,
        )
        self.assertEqual(restored.reactionStatus, "published")


if __name__ == "__main__":
    unittest.main()
