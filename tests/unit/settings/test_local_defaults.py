from unittest import mock

from i4g.settings.config import DEFAULT_CONFIG_FILE, reload_settings


def test_local_env_sets_default_pepper(monkeypatch):
    """Ensure local environment gets a default pepper if none is provided."""
    monkeypatch.setenv("I4G_ENV", "local")
    monkeypatch.delenv("I4G_PII__PEPPER", raising=False)
    monkeypatch.delenv("I4G_TOKENIZATION__PEPPER", raising=False)

    # Mock _config_file_priority to only return default config, ignoring local config
    with mock.patch("i4g.settings.config._config_file_priority") as mock_priority:
        mock_priority.return_value = (DEFAULT_CONFIG_FILE,)

        settings = reload_settings(env="local")
        assert settings.pii.pepper == "local-secret-pepper"


def test_prod_env_does_not_set_default_pepper(monkeypatch):
    """Ensure prod environment does NOT get a default pepper."""
    monkeypatch.setenv("I4G_ENV", "prod")
    monkeypatch.delenv("I4G_PII__PEPPER", raising=False)
    monkeypatch.delenv("I4G_TOKENIZATION__PEPPER", raising=False)

    # Mock _config_file_priority to only return default config
    with mock.patch("i4g.settings.config._config_file_priority") as mock_priority:
        mock_priority.return_value = (DEFAULT_CONFIG_FILE,)

        settings = reload_settings(env="prod")
        assert settings.pii.pepper is None


def test_local_env_respects_override(monkeypatch):
    """Ensure explicit override is respected even in local."""
    monkeypatch.setenv("I4G_ENV", "local")
    monkeypatch.setenv("I4G_PII__PEPPER", "custom-pepper")

    # Mock _config_file_priority to only return default config
    with mock.patch("i4g.settings.config._config_file_priority") as mock_priority:
        mock_priority.return_value = (DEFAULT_CONFIG_FILE,)

        settings = reload_settings(env="local")
        assert settings.pii.pepper == "custom-pepper"
