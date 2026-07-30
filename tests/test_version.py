from app.version import APP_VERSION, RELEASE_NAME, __version__


def test_version_module_exposes_conventional_version_attribute():
    assert __version__ == APP_VERSION
    assert __version__ == "5.3.3"
    assert RELEASE_NAME
