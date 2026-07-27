from pathlib import Path
import tomllib


def test_railway_toml_is_valid_and_has_expected_deploy_settings():
    config_path = Path(__file__).resolve().parents[1] / "railway.toml"
    raw = config_path.read_bytes()

    # Railway expects a plain TOML file, not Markdown/Python or a UTF-8 BOM.
    assert not raw.startswith(b"\xef\xbb\xbf")

    config = tomllib.loads(raw.decode("utf-8"))
    deploy = config["deploy"]

    assert deploy["startCommand"] == "/app/entrypoint.sh"
    assert deploy["restartPolicyType"] == "NEVER"
    assert deploy["cronSchedule"] == "0 */6 * * *"
