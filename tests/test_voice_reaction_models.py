import unittest

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import (
    Brand,
    City,
    Country,
    MediaAsset,
    Product,
    User,
    VoiceReaction,
)


class VoiceReactionModelTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(dbapi_connection, _connection_record):
            dbapi_connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        country = Country(code="US", name="United States")
        city = City(
            slug="new-york",
            name="New York",
            country=country,
            latitude=40.7128,
            longitude=-74.0060,
        )
        brand = Brand(name="Voice Test Brand", country=country)
        user = User(id="creator-1", email="creator@example.test")
        product = Product(
            external_id="voice-test-product",
            source="test",
            name="Voice Test Product",
            currency="USD",
            brand=brand,
            city=city,
        )
        self.db.add_all([country, city, brand, user, product])
        self.db.commit()

        self.city_id = city.id
        self.product_id = product.id
        self.user_id = user.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _create_reaction(self, *, storage_key: str = "voice/user/take.webm"):
        reaction = VoiceReaction(
            product_id=self.product_id,
            user_id=self.user_id,
            city_id=self.city_id,
            reaction_tag="would_compliment",
        )
        reaction.media_asset = MediaAsset(
            storage_key=storage_key,
            mime_type="audio/webm",
        )
        self.db.add(reaction)
        self.db.commit()
        return reaction

    def test_relationships_and_lifecycle_defaults(self):
        reaction = self._create_reaction()

        self.assertEqual(reaction.product.id, self.product_id)
        self.assertEqual(reaction.user.id, self.user_id)
        self.assertEqual(reaction.city.id, self.city_id)
        self.assertIs(reaction.media_asset.voice_reaction, reaction)
        self.assertEqual(reaction.status, "pending")
        self.assertEqual(reaction.media_asset.status, "pending")
        self.assertEqual(reaction.media_asset.storage_provider, "s3_compatible")
        self.assertEqual(reaction.media_asset.extra_metadata, {})

    def test_reaction_tag_is_database_constrained(self):
        self.db.add(
            VoiceReaction(
                product_id=self.product_id,
                user_id=self.user_id,
                reaction_tag="anything_goes",
            )
        )

        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_general_reaction_experience_and_optional_compliment_are_constrained(self):
        reaction = VoiceReaction(
            product_id=self.product_id,
            user_id=self.user_id,
            reaction_tag="general",
            experience_type="wore_it",
            compliment_response="yes",
        )
        self.db.add(reaction)
        self.db.commit()

        self.assertEqual(reaction.experience_type, "wore_it")
        self.assertEqual(reaction.compliment_response, "yes")

        invalid_reactions = (
            VoiceReaction(
                product_id=self.product_id,
                user_id=self.user_id,
                reaction_tag="general",
                experience_type="wore_it",
                compliment_response="not_sure",
            ),
            VoiceReaction(
                product_id=self.product_id,
                user_id=self.user_id,
                reaction_tag="general",
                experience_type=None,
                compliment_response="yes",
            ),
        )
        for index, invalid_reaction in enumerate(invalid_reactions):
            with self.subTest(index=index):
                self.db.add(invalid_reaction)
                with self.assertRaises(IntegrityError):
                    self.db.commit()
                self.db.rollback()

    def test_reaction_status_is_database_constrained(self):
        self.db.add(
            VoiceReaction(
                product_id=self.product_id,
                user_id=self.user_id,
                reaction_tag="great_fit",
                status="ready",
            )
        )

        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_media_status_mime_size_and_duration_are_database_constrained(self):
        invalid_values = (
            {"status": "playable"},
            {"mime_type": "application/octet-stream"},
            {"file_size_bytes": -1},
            {"duration_ms": 0},
        )

        for index, overrides in enumerate(invalid_values):
            with self.subTest(overrides=overrides):
                reaction = VoiceReaction(
                    product_id=self.product_id,
                    user_id=self.user_id,
                    reaction_tag="would_wear",
                )
                values = {
                    "storage_key": f"voice/user/invalid-{index}.webm",
                    "mime_type": "audio/webm",
                    **overrides,
                }
                reaction.media_asset = MediaAsset(**values)
                self.db.add(reaction)
                with self.assertRaises(IntegrityError):
                    self.db.commit()
                self.db.rollback()

    def test_user_and_city_deletion_preserve_reaction_with_null_attribution(self):
        reaction = self._create_reaction()
        reaction_id = reaction.id

        self.db.delete(self.db.get(User, self.user_id))
        self.db.delete(self.db.get(City, self.city_id))
        self.db.commit()

        preserved = self.db.get(VoiceReaction, reaction_id)
        self.assertIsNotNone(preserved)
        self.assertIsNone(preserved.user_id)
        self.assertIsNone(preserved.city_id)

    def test_product_deletion_cascades_reaction_and_media_metadata(self):
        reaction = self._create_reaction()
        reaction_id = reaction.id
        media_asset_id = reaction.media_asset.id
        self.db.expire_all()

        self.db.delete(self.db.get(Product, self.product_id))
        self.db.commit()

        self.assertIsNone(self.db.get(VoiceReaction, reaction_id))
        self.assertIsNone(self.db.get(MediaAsset, media_asset_id))

    def test_voice_reaction_has_at_most_one_media_asset(self):
        reaction = self._create_reaction()
        self.db.add(
            MediaAsset(
                voice_reaction_id=reaction.id,
                storage_key="voice/user/second.webm",
                mime_type="audio/webm",
            )
        )

        with self.assertRaises(IntegrityError):
            self.db.commit()
        self.db.rollback()

    def test_known_access_patterns_have_targeted_indexes(self):
        inspector = inspect(self.engine)
        voice_indexes = {
            index["name"]: index["column_names"]
            for index in inspector.get_indexes("voice_reactions")
        }
        media_indexes = {
            index["name"]: index["column_names"]
            for index in inspector.get_indexes("media_assets")
        }

        self.assertEqual(
            voice_indexes["ix_voice_reactions_product_status_created_at"],
            ["product_id", "status", "created_at"],
        )
        self.assertEqual(
            media_indexes["ix_media_assets_status_created_at"],
            ["status", "created_at"],
        )


if __name__ == "__main__":
    unittest.main()
