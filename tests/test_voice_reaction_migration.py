import importlib.util
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


MIGRATION_PATH = (
    Path(__file__).parents[1]
    / "alembic"
    / "versions"
    / "c3d4e5f6a7b8_add_voice_reaction_foundation.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location(
        "voice_reaction_foundation_migration",
        MIGRATION_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load voice reaction migration")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class VoiceReactionMigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade_are_reversible(self):
        engine = create_engine("sqlite:///:memory:")
        migration = _load_migration()

        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE users (id VARCHAR(64) PRIMARY KEY)"))
                connection.execute(text("CREATE TABLE cities (id INTEGER PRIMARY KEY)"))
                connection.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY)"))

                operations = Operations(MigrationContext.configure(connection))
                original_op = migration.op
                migration.op = operations
                try:
                    migration.upgrade()
                    inspector = inspect(connection)
                    self.assertIn("voice_reactions", inspector.get_table_names())
                    self.assertIn("media_assets", inspector.get_table_names())
                    self.assertIn(
                        "ix_voice_reactions_product_status_created_at",
                        {
                            index["name"]
                            for index in inspector.get_indexes("voice_reactions")
                        },
                    )

                    migration.downgrade()
                    remaining_tables = set(inspect(connection).get_table_names())
                    self.assertNotIn("voice_reactions", remaining_tables)
                    self.assertNotIn("media_assets", remaining_tables)
                finally:
                    migration.op = original_op
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
