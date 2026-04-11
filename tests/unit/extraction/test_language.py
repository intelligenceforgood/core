"""Tests for i4g.extraction.language — language detection and prompt hints."""

from __future__ import annotations

from i4g.extraction.language import build_language_hint, detect_language


class TestDetectLanguage:

    def test_english_text(self):
        text = "This is a fairly long English sentence for detection testing purposes."
        assert detect_language(text) == "en"

    def test_spanish_text(self):
        text = "Este es un texto largo en español para probar la detección de idioma correctamente."
        result = detect_language(text)
        assert result == "es"

    def test_short_text_defaults_to_english(self):
        assert detect_language("Hi") == "en"

    def test_empty_text_defaults_to_english(self):
        assert detect_language("") == "en"


class TestBuildLanguageHint:

    def test_english_returns_empty(self):
        assert build_language_hint("en") == ""

    def test_en_us_returns_empty(self):
        assert build_language_hint("en-us") == ""

    def test_spanish_returns_hint(self):
        hint = build_language_hint("es")
        assert "Spanish" in hint
        assert "IMPORTANT" in hint

    def test_chinese_returns_hint(self):
        hint = build_language_hint("zh-cn")
        assert "Chinese" in hint

    def test_unknown_code_uses_uppercase(self):
        hint = build_language_hint("xx")
        assert "XX" in hint
