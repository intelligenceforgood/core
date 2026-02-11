"""Unit tests for i4g.utils.coerce."""

from __future__ import annotations

import os

import pytest

from i4g.utils.coerce import coerce_bool, env_bool, env_int, env_list


# ── coerce_bool ──────────────────────────────────────────────────────


class TestCoerceBool:
    @pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON"])
    def test_truthy_values(self, value: str) -> None:
        assert coerce_bool(value) is True

    @pytest.mark.parametrize("value", ["0", "false", "False", "FALSE", "no", "NO", "off", "OFF"])
    def test_falsy_values(self, value: str) -> None:
        assert coerce_bool(value) is False

    def test_none_returns_none(self) -> None:
        assert coerce_bool(None) is None

    def test_unrecognised_returns_none(self) -> None:
        assert coerce_bool("maybe") is None
        assert coerce_bool("2") is None

    def test_whitespace_is_stripped(self) -> None:
        assert coerce_bool("  true  ") is True
        assert coerce_bool("  false  ") is False


# ── env_bool ─────────────────────────────────────────────────────────


class TestEnvBool:
    def test_returns_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_ENV_BOOL_X", raising=False)
        assert env_bool("TEST_ENV_BOOL_X") is False
        assert env_bool("TEST_ENV_BOOL_X", default=True) is True

    def test_truthy_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_ENV_BOOL_X", "true")
        assert env_bool("TEST_ENV_BOOL_X") is True

    def test_falsy_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_ENV_BOOL_X", "0")
        assert env_bool("TEST_ENV_BOOL_X") is False


# ── env_int ──────────────────────────────────────────────────────────


class TestEnvInt:
    def test_returns_default_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_ENV_INT_X", raising=False)
        assert env_int("TEST_ENV_INT_X", 42) == 42

    def test_parses_integer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_ENV_INT_X", "7")
        assert env_int("TEST_ENV_INT_X", 0) == 7

    def test_empty_string_returns_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_ENV_INT_X", "  ")
        assert env_int("TEST_ENV_INT_X", 99) == 99

    def test_non_integer_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_ENV_INT_X", "abc")
        with pytest.raises(ValueError, match="must be an integer"):
            env_int("TEST_ENV_INT_X", 0)


# ── env_list ─────────────────────────────────────────────────────────


class TestEnvList:
    def test_returns_empty_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TEST_ENV_LIST_X", raising=False)
        assert env_list("TEST_ENV_LIST_X") == []

    def test_returns_empty_for_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_ENV_LIST_X", "")
        assert env_list("TEST_ENV_LIST_X") == []

    def test_splits_and_lowercases(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_ENV_LIST_X", "PDF, csv , HTML")
        assert env_list("TEST_ENV_LIST_X") == ["pdf", "csv", "html"]

    def test_strips_whitespace_and_skips_blanks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_ENV_LIST_X", " a , , b ")
        assert env_list("TEST_ENV_LIST_X") == ["a", "b"]
