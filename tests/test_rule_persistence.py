"""Default presets must preserve user deletions, including existing databases."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import database
from app.models.schemas import SmartRule


@pytest.fixture
def isolated_db(monkeypatch, tmp_path):
    path = tmp_path / "rules.sqlite"
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(database, "db_path", str(path))
    yield
    engine.dispose()


def test_deleted_defaults_do_not_reappear_on_startup(isolated_db):
    database.init_db()
    original = database.get_all_rules()
    assert original
    removed = original[0]
    database.delete_rule(removed.id)
    database.init_db()
    assert removed.name not in {rule.name for rule in database.get_all_rules()}


def test_deleting_all_defaults_remains_empty_after_restart(isolated_db):
    database.init_db()
    for rule in database.get_all_rules():
        database.delete_rule(rule.id)
    database.init_db()
    assert database.get_all_rules() == []


def test_explicit_restore_adds_missing_defaults_without_duplicates(isolated_db):
    database.init_db()
    database.delete_rule(database.get_all_rules()[0].id)
    database._seed_default_rules_if_empty(force=True)
    count = len(database.get_all_rules())
    database._seed_default_rules_if_empty(force=True)
    assert len(database.get_all_rules()) == count == 5


def test_legacy_database_with_all_rules_deleted_is_preserved(isolated_db):
    database.Base.metadata.create_all(database.engine)
    database.init_db()
    assert database.get_all_rules() == []
    assert database.get_setting("default_rules_initialized") == "true"


def test_legacy_custom_rules_are_preserved_without_reseeding(isolated_db):
    database.Base.metadata.create_all(database.engine)
    database.create_rule("My Rule", "contains", "special", "special-folder")
    database.init_db()
    assert [rule.name for rule in database.get_all_rules()] == ["My Rule"]


def test_factory_reset_restores_initial_presets(isolated_db):
    database.init_db()
    for rule in database.get_all_rules():
        database.delete_rule(rule.id)
    database.reset_database()
    assert len(database.get_all_rules()) == 5
