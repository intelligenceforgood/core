"""Tests for the extraction orchestrator — i4g.extraction.orchestrator."""

from __future__ import annotations

from i4g.extraction.orchestrator import extract_entities
from i4g.extraction.types import ExtractionResult, ModuleStatus


class _MockLLMClient:
    """Minimal mock that satisfies the LLMClient protocol."""

    def __init__(self, response: str = "{}") -> None:
        self._response = response

    def generate(self, prompt: str) -> str:
        return self._response


class _FailingLLMClient:
    def generate(self, prompt: str) -> str:
        raise RuntimeError("LLM unavailable")


class TestOrchestratorBasic:
    """End-to-end orchestrator tests with real modules."""

    def test_regex_only(self):
        """Regex module should extract wallets, emails, etc."""
        text = "Send to 0xAbCdEf1234567890AbCdEf1234567890AbCdEf12 or email alice@example.com"
        result = extract_entities(text, modules=["regex"])

        assert isinstance(result, ExtractionResult)
        assert len(result.module_reports) == 1
        assert result.module_reports[0].module_name == "regex"
        assert result.module_reports[0].status == ModuleStatus.SUCCESS

        types = {e.entity_type for e in result.entities}
        assert "wallet_address" in types or "email_address" in types

    def test_regex_finds_email(self):
        text = "Contact support@example.com for help"
        result = extract_entities(text, modules=["regex"])

        emails = [e for e in result.entities if e.entity_type == "email_address"]
        assert len(emails) == 1
        assert "example.com" in emails[0].canonical_value

    def test_empty_text_returns_empty(self):
        result = extract_entities("", modules=["regex"])
        assert result.entities == []

    def test_no_modules_returns_empty(self):
        result = extract_entities("some text", modules=[])
        assert result.entities == []


class TestOrchestratorWithLLM:
    def test_llm_module_with_mock_client(self):
        """LLM module should produce entities from mock response."""
        import json

        llm_response = json.dumps(
            {
                "people": ["Alice Smith"],
                "organizations": ["FraudCorp"],
                "wallet_addresses": [],
                "bank_accounts": [],
                "email_addresses": [],
                "phone_numbers": [],
                "urls": [],
                "domains": [],
                "social_handles": [],
                "crypto_assets": [],
                "locations": [],
                "scam_indicators": ["urgent payment request"],
            }
        )

        result = extract_entities(
            "Alice Smith from FraudCorp asked for an urgent payment",
            modules=["llm"],
            llm_client=_MockLLMClient(llm_response),
            confidence_gates={"person": 0.0, "organization": 0.0, "scam_indicator": 0.0},
        )

        assert len(result.module_reports) == 1
        assert result.module_reports[0].module_name == "llm"

        names = [e for e in result.entities if e.entity_type == "person"]
        orgs = [e for e in result.entities if e.entity_type == "organization"]
        assert len(names) >= 1
        assert len(orgs) >= 1

    def test_llm_failure_graceful_fallback(self):
        """When LLM fails, module returns empty but doesn't crash the pipeline."""
        result = extract_entities(
            "Send to 0xAbCdEf1234567890AbCdEf1234567890AbCdEf12",
            modules=["regex", "llm"],
            llm_client=_FailingLLMClient(),
            confidence_gates={"wallet_address": 0.0},
        )

        # Regex module should still produce results
        regex_report = next(r for r in result.module_reports if r.module_name == "regex")
        llm_report = next(r for r in result.module_reports if r.module_name == "llm")
        assert regex_report.status == ModuleStatus.SUCCESS
        # LLM module catches its own exceptions and returns [] — orchestrator
        # sees SUCCESS with 0 entities (the failure is logged internally).
        assert llm_report.status == ModuleStatus.SUCCESS
        assert llm_report.entity_count == 0

        # Should still have regex entities
        wallets = [e for e in result.entities if e.entity_type == "wallet_address"]
        assert len(wallets) >= 1


class TestOrchestratorMerge:
    """Test that the merge logic is applied correctly through the orchestrator."""

    def test_wells_fargo_blocked(self):
        """The 'Wells Fargo' false positive should be blocked by the merge engine."""
        import json

        llm_response = json.dumps(
            {
                "people": ["Wells Fargo", "Alice Smith"],
                "organizations": [],
                "wallet_addresses": [],
                "bank_accounts": [],
                "email_addresses": [],
                "phone_numbers": [],
                "urls": [],
                "domains": [],
                "social_handles": [],
                "crypto_assets": [],
                "locations": [],
                "scam_indicators": [],
            }
        )

        result = extract_entities(
            "Wells Fargo contacted Alice Smith about wire transfer.",
            modules=["llm"],
            llm_client=_MockLLMClient(llm_response),
            confidence_gates={"person": 0.0},
            include_merge_log=True,
        )

        person_values = {e.canonical_value.lower() for e in result.entities if e.entity_type == "person"}
        assert "wells fargo" not in person_values
        assert "alice smith" in person_values

        # Wells Fargo should appear as DROPPED in merge log
        dropped = [d for d in result.merge_log if d.value.lower() == "wells fargo"]
        assert len(dropped) == 1
        assert dropped[0].action.value == "dropped"

    def test_multi_source_agreement_through_orchestrator(self):
        """When regex and LLM both find same email, confidence should be boosted."""
        import json

        llm_response = json.dumps(
            {
                "people": [],
                "organizations": [],
                "wallet_addresses": [],
                "bank_accounts": [],
                "email_addresses": ["scammer@evil.com"],
                "phone_numbers": [],
                "urls": [],
                "domains": [],
                "social_handles": [],
                "crypto_assets": [],
                "locations": [],
                "scam_indicators": [],
            }
        )

        result = extract_entities(
            "Contact scammer@evil.com for the deal",
            modules=["regex", "llm"],
            llm_client=_MockLLMClient(llm_response),
            confidence_gates={"email_address": 0.0},
            include_merge_log=True,
        )

        emails = [e for e in result.entities if e.entity_type == "email_address"]
        assert len(emails) == 1
        # Both regex (1.0*0.9=0.9) and LLM (0.7*0.7=0.49) found it.
        # max = 0.9, + 0.1 bonus = 1.0
        assert emails[0].confidence == 1.0

        # Check merge log shows BOOSTED
        email_decisions = [d for d in result.merge_log if d.entity_type == "email_address"]
        assert any(d.action.value == "boosted" for d in email_decisions)


class TestOrchestratorSettingsIntegration:
    """Verify that the orchestrator reads from settings when args not provided."""

    def test_uses_settings_default_modules(self):
        """When modules=None, should use settings.extraction.enabled_modules."""
        # The default settings have ["regex", "llm"] — but LLM needs a client.
        # Without providing one, the LLM module is skipped with a warning.
        result = extract_entities(
            "test@example.com",
            # modules=None → reads from settings
        )
        # Should still get regex results since regex doesn't need external deps
        module_names = [r.module_name for r in result.module_reports]
        assert "regex" in module_names


class TestOrchestratorObfuscation:
    """Verify that the orchestrator de-obfuscates text before module dispatch."""

    def test_obfuscated_email_extracted(self):
        """Regex module should find email after 'dot' / 'at' de-obfuscation."""
        result = extract_entities(
            "Contact alice at example dot com for help",
            modules=["regex"],
            confidence_gates={"email_address": 0.0},
        )
        emails = [e for e in result.entities if e.entity_type == "email_address"]
        assert len(emails) == 1
        assert "example.com" in emails[0].canonical_value

    def test_leetspeak_domain_extracted(self):
        """De-obfuscation should decode leetspeak for known domains before regex."""
        result = extract_entities(
            "Visit g00gle dot com for support",
            modules=["regex"],
            confidence_gates={"url": 0.0, "domain": 0.0},
        )
        # After de-obfuscation: "Visit google.com for support"
        # Regex should find a URL or domain
        values = {e.canonical_value for e in result.entities}
        assert any("google.com" in v for v in values)
