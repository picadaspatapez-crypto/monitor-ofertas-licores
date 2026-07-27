from pathlib import Path


def test_search_service_starts_web_and_telegram_together():
    root = Path(__file__).resolve().parents[1]
    entrypoint = (root / "search_entrypoint.sh").read_text(encoding="utf-8")
    service = (root / "app/search/service.py").read_text(encoding="utf-8")
    requirements = (root / "requirements-search.txt").read_text(encoding="utf-8")

    assert "python -m app.search.service" in entrypoint
    assert "TelegramSearchBot" in service
    assert "SearchServer" in service
    assert "requests==2.32.3" in requirements


def test_telegram_state_migration_follows_search_catalog():
    root = Path(__file__).resolve().parents[1]
    migration = (
        root / "alembic/versions/0006_telegram_bot_state.py"
    ).read_text(encoding="utf-8")
    assert 'revision = "0006_telegram_bot_state"' in migration
    assert 'down_revision = "0005_search_catalog"' in migration
