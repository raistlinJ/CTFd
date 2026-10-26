import os
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory

from CTFd import create_app
from CTFd.config import TestingConfig
from CTFd.models import Solves, Submissions, Users
from CTFd.utils import get_config, set_config
from tests.helpers import create_ctfd, destroy_ctfd, gen_challenge, gen_solve, gen_user


CURRENT_REVISION = "a3e1c5d7b9f2"


def test_retraction_build_recognizes_current_database_revision():
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "migrations/alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_revision(CURRENT_REVISION).revision == CURRENT_REVISION
    assert scripts.get_heads() == [CURRENT_REVISION]


@pytest.mark.skipif(
    not os.environ.get("TESTING_DATABASE_URL", "").startswith("mysql"),
    reason="Requires the MySQL/MariaDB startup migration path",
)
def test_startup_on_current_mariadb_schema_preserves_existing_submissions():
    app = create_ctfd(enable_plugins=True)
    try:
        with app.app_context():
            user = gen_user(app.db)
            challenge = gen_challenge(app.db)
            solve = gen_solve(app.db, user_id=user.id, challenge_id=challenge.id)
            user_id, solve_id = user.id, solve.id
            set_config("allow_solve_retraction", True)
            database_url = app.config["SQLALCHEMY_DATABASE_URI"]
            with app.db.engine.connect() as connection:
                assert (
                    MigrationContext.configure(connection).get_current_revision()
                    == CURRENT_REVISION
                )

        class ExistingDatabaseConfig(TestingConfig):
            SQLALCHEMY_DATABASE_URI = database_url
            SAFE_MODE = False

        # Exercise the same application startup/upgrade that previously failed.
        restarted = create_app(ExistingDatabaseConfig)
        with restarted.app_context():
            assert Users.query.get(user_id) is not None
            assert Solves.query.get(solve_id) is not None
            assert Submissions.query.filter_by(user_id=user_id).count() == 1
            assert bool(get_config("allow_solve_retraction")) is True
            with restarted.db.engine.connect() as connection:
                assert (
                    MigrationContext.configure(connection).get_current_revision()
                    == CURRENT_REVISION
                )
    finally:
        destroy_ctfd(app)
