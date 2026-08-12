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
    / "d4e5f6a7b8c9_add_voice_reaction_reporting.py"
)


class VoiceReactionReportingMigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade_are_reversible(self):
        spec = importlib.util.spec_from_file_location(
            "voice_reaction_reporting_migration",
            MIGRATION_PATH,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("could not load voice reaction reporting migration")
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        engine = create_engine("sqlite:///:memory:")

        try:
            with engine.begin() as connection:
                connection.execute(text("CREATE TABLE users (id VARCHAR(64) PRIMARY KEY)"))
                connection.execute(
                    text("CREATE TABLE voice_reactions (id BIGINT PRIMARY KEY)")
                )
                operations = Operations(MigrationContext.configure(connection))
                original_op = migration.op
                migration.op = operations
                try:
                    migration.upgrade()
                    inspector = inspect(connection)
                    self.assertIn(
                        "voice_reaction_reports",
                        inspector.get_table_names(),
                    )
                    self.assertIn(
                        "ix_voice_reaction_reports_status_created_at",
                        {
                            index["name"]
                            for index in inspector.get_indexes(
                                "voice_reaction_reports"
                            )
                        },
                    )

                    migration.downgrade()
                    self.assertNotIn(
                        "voice_reaction_reports",
                        inspect(connection).get_table_names(),
                    )
                finally:
                    migration.op = original_op
        finally:
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
