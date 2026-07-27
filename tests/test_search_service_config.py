from pathlib import Path
import tomllib


def test_search_railway_config_is_always_on_and_has_healthcheck():
    path = Path(__file__).resolve().parents[1] / "railway.search.toml"
    config = tomllib.loads(path.read_text(encoding="utf-8"))
    assert config["build"]["dockerfilePath"] == "Dockerfile.search"
    deploy = config["deploy"]
    assert deploy["startCommand"] == "/app/search_entrypoint.sh"
    assert deploy["restartPolicyType"] == "ALWAYS"
    assert deploy["healthcheckPath"] == "/health"
    assert "cronSchedule" not in deploy


def test_search_entrypoint_runs_migrations_and_web_server():
    path = Path(__file__).resolve().parents[1] / "search_entrypoint.sh"
    text = path.read_text(encoding="utf-8")
    assert "alembic upgrade head" in text
    assert "python -m app.search.reindex" in text
    assert "python -m app.search.service" in text
