import importlib.util
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


VERSIONS_PATH = Path(__file__).parents[1] / "alembic" / "versions"


def _load_migration(filename: str, module_name: str):
    spec = importlib.util.spec_from_file_location(
        module_name,
        VERSIONS_PATH / filename,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VoiceReactionExperienceMigrationTests(unittest.TestCase):
    def test_upgrade_preserves_legacy_rows_and_adds_nullable_experience_fields(self):
        engine = create_engine("sqlite:///:memory:")
        foundation = _load_migration(
            "c3d4e5f6a7b8_add_voice_reaction_foundation.py",
            "voice_reaction_foundation_for_experience",
        )
        experience = _load_migration(
            "e5f6a7b8c9d0_add_voice_reaction_experience.py",
            "voice_reaction_experience_migration",
        )

        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE users (id VARCHAR(64) PRIMARY KEY)"))
                connection.execute(text("CREATE TABLE cities (id INTEGER PRIMARY KEY)"))
                connection.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY)"))
                operations = Operations(MigrationContext.configure(connection))

                original_foundation_op = foundation.op
                original_experience_op = experience.op
                foundation.op = operations
                experience.op = operations
                try:
                    foundation.upgrade()
                    connection.execute(
                        text(
                            "INSERT INTO voice_reactions "
                            "(id, product_id, reaction_tag, status) "
                            "VALUES (1, 1, 'great_fit', 'published')"
                        )
                    )

                    experience.upgrade()

                    columns = {
                        column["name"]
                        for column in inspect(connection).get_columns("voice_reactions")
                    }
                    self.assertIn("experience_type", columns)
                    self.assertIn("compliment_response", columns)
                    legacy = connection.execute(
                        text(
                            "SELECT reaction_tag, experience_type, compliment_response "
                            "FROM voice_reactions WHERE id = 1"
                        )
                    ).one()
                    self.assertEqual(legacy.reaction_tag, "great_fit")
                    self.assertIsNone(legacy.experience_type)
                    self.assertIsNone(legacy.compliment_response)

                    connection.execute(
                        text(
                            "INSERT INTO voice_reactions "
                            "(id, product_id, reaction_tag, experience_type, "
                            "compliment_response, status) VALUES "
                            "(2, 1, 'general', 'first_impression', 'not_sure', "
                            "'published')"
                        )
                    )
                    connection.execute(text("DELETE FROM voice_reactions WHERE id = 2"))
                    experience.downgrade()
                    downgraded_columns = {
                        column["name"]
                        for column in inspect(connection).get_columns("voice_reactions")
                    }
                    self.assertNotIn("experience_type", downgraded_columns)
                    self.assertNotIn("compliment_response", downgraded_columns)
                finally:
                    foundation.op = original_foundation_op
                    experience.op = original_experience_op
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
