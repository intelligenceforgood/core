"""Tests for i4g.extraction.modules.blocklist — blocklist filter module."""

from __future__ import annotations

from pathlib import Path

from i4g.extraction.modules.blocklist import BlocklistModule
from i4g.extraction.types import ModuleProtocol


class TestBlocklistModuleProtocol:
    def test_implements_protocol(self):
        m = BlocklistModule()
        assert isinstance(m, ModuleProtocol)

    def test_name(self):
        assert BlocklistModule().name == "blocklist"

    def test_authority_empty(self):
        assert BlocklistModule().authority == {}

    def test_extract_is_noop(self):
        assert BlocklistModule().extract("anything") == []


class TestBlocklistFiltering:
    def test_wells_fargo_blocked_as_person(self):
        m = BlocklistModule()
        assert m.is_blocklisted("person", "Wells Fargo") is True

    def test_chase_bank_blocked_as_person(self):
        m = BlocklistModule()
        assert m.is_blocklisted("person", "Chase Bank") is True

    def test_on_behalf_blocked_as_person(self):
        m = BlocklistModule()
        assert m.is_blocklisted("person", "On Behalf") is True

    def test_united_states_blocked_as_person(self):
        m = BlocklistModule()
        assert m.is_blocklisted("person", "United States") is True

    def test_banking_labels_blocked_as_person(self):
        m = BlocklistModule()
        assert m.is_blocklisted("person", "Account Number") is True
        assert m.is_blocklisted("person", "Bank Name") is True
        assert m.is_blocklisted("person", "Wire Transfer") is True
        assert m.is_blocklisted("person", "Sort Code") is True

    def test_scam_terms_blocked_as_person(self):
        m = BlocklistModule()
        assert m.is_blocklisted("person", "Advance Fee") is True
        assert m.is_blocklisted("person", "Money Mule") is True
        assert m.is_blocklisted("person", "Romance Scam") is True

    def test_real_name_not_blocked(self):
        m = BlocklistModule()
        assert m.is_blocklisted("person", "John Doe") is False

    def test_case_insensitive(self):
        m = BlocklistModule()
        assert m.is_blocklisted("person", "wells fargo") is True
        assert m.is_blocklisted("person", "WELLS FARGO") is True
        assert m.is_blocklisted("person", "Wells Fargo") is True

    def test_unknown_type_not_blocked(self):
        m = BlocklistModule()
        # "Wells Fargo" is only blocked for type "person", not "organization"
        assert m.is_blocklisted("organization", "Wells Fargo") is False

    def test_day_prefix_blocked(self):
        m = BlocklistModule()
        assert m.is_blocklisted("person", "On Mon") is True
        assert m.is_blocklisted("person", "On Wed") is True

    def test_original_message_blocked(self):
        m = BlocklistModule()
        assert m.is_blocklisted("person", "Original Message") is True


class TestBlocklistCustomConfig:
    def test_nonexistent_file_uses_defaults(self):
        m = BlocklistModule(config_path=Path("/nonexistent/file.toml"))
        # Still has default blocklist
        assert m.is_blocklisted("person", "Wells Fargo") is True

    def test_custom_toml_extends_defaults(self, tmp_path: Path):
        toml_content = b'[person]\nvalues = ["Custom Fake Name"]\n'
        config = tmp_path / "blocklist.toml"
        config.write_bytes(toml_content)

        m = BlocklistModule(config_path=config)
        # Custom entry added
        assert m.is_blocklisted("person", "Custom Fake Name") is True
        # Defaults still present
        assert m.is_blocklisted("person", "Wells Fargo") is True

    def test_custom_toml_adds_new_type(self, tmp_path: Path):
        toml_content = b'[organization]\nvalues = ["Scam Corp"]\n'
        config = tmp_path / "blocklist.toml"
        config.write_bytes(toml_content)

        m = BlocklistModule(config_path=config)
        assert m.is_blocklisted("organization", "Scam Corp") is True
