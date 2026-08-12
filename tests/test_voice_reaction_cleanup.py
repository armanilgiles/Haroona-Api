import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.media.storage import MediaStorageOperationError
from app.media.voice_cleanup import cleanup_stale_voice_uploads
from app.models import Brand, Country, MediaAsset, Product, User, VoiceReaction


class VoiceReactionCleanupTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(dbapi_connection, _connection_record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        country = Country(code="US", name="United States")
        brand = Brand(name="Cleanup Brand", country=country)
        self.user = User(id="cleanup-user", email="cleanup@example.test")
        self.product = Product(
            external_id="cleanup-product",
            source="test",
            name="Cleanup Product",
            currency="USD",
            brand=brand,
        )
        self.db.add_all([country, brand, self.user, self.product])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _pending(self, *, age: timedelta, key: str) -> VoiceReaction:
        reaction = VoiceReaction(
            product_id=self.product.id,
            user_id=self.user.id,
            reaction_tag="would_wear",
            status="pending",
            created_at=datetime.now(UTC) - age,
        )
        reaction.media_asset = MediaAsset(
            storage_key=key,
            mime_type="audio/webm",
            file_size_bytes=10,
            duration_ms=1000,
            status="pending",
        )
        self.db.add(reaction)
        self.db.commit()
        return reaction

    def test_cleanup_expires_only_stale_pending_rows(self):
        stale = self._pending(age=timedelta(hours=2), key="voice/a/stale.webm")
        fresh = self._pending(age=timedelta(minutes=10), key="voice/a/fresh.webm")

        with patch(
            "app.media.voice_cleanup.delete_media_object",
            side_effect=MediaStorageOperationError("temporary"),
        ):
            result = cleanup_stale_voice_uploads(self.db)

        self.db.refresh(stale)
        self.db.refresh(fresh)
        self.assertEqual(stale.status, "deleted")
        self.assertEqual(stale.media_asset.status, "deleted")
        self.assertEqual(fresh.status, "pending")
        self.assertEqual(result.expired, 1)
        self.assertEqual(result.object_delete_failures, 1)


if __name__ == "__main__":
    unittest.main()
