"""Tests for i4g.cli.bootstrap.synthetic_coverage — deterministic synthetic data generation."""

from __future__ import annotations

import random

from i4g.cli.bootstrap.synthetic_coverage import (
    Scenario,
    _rand_amount,
    _rand_phone,
    _rand_ticket,
    _rand_wallet,
    build_cases,
    build_ground_truth,
    build_saved_searches,
    build_scenarios,
    make_summary,
)

# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


class TestMakeSummary:
    def test_first_sentence(self):
        assert make_summary("Hello. World.") == "Hello"

    def test_single_sentence(self):
        assert make_summary("Just one sentence") == "Just one sentence"

    def test_strips_whitespace(self):
        assert make_summary("  Leading spaces. More.  ") == "Leading spaces"


class TestRandAmount:
    def test_in_range(self):
        rng = random.Random(42)
        for _ in range(50):
            amount = _rand_amount(10.0, 100.0, rng)
            assert 10.0 <= amount <= 100.0

    def test_precision(self):
        rng = random.Random(42)
        amount = _rand_amount(0.0, 1.0, rng, precision=4)
        parts = str(amount).split(".")
        if len(parts) == 2:
            assert len(parts[1]) <= 4


class TestRandWallet:
    def test_btc_prefixes(self):
        rng = random.Random(42)
        wallet = _rand_wallet("BTC", rng)
        assert wallet[0] in ("1", "3", "b")

    def test_eth_prefix(self):
        rng = random.Random(42)
        wallet = _rand_wallet("ETH", rng)
        assert wallet.startswith("0x")
        assert len(wallet) == 42

    def test_usdt_is_evm(self):
        rng = random.Random(42)
        wallet = _rand_wallet("USDT", rng)
        assert wallet.startswith("0x")


class TestRandPhone:
    def test_format(self):
        rng = random.Random(42)
        phone = _rand_phone(rng)
        assert phone.startswith("+1-877-")
        # Format is +1-877-XXX-XXXX
        assert len(phone.split("-")) >= 3


class TestRandTicket:
    def test_format(self):
        rng = random.Random(42)
        ticket = _rand_ticket(rng)
        assert ticket.startswith("TX-")
        assert ticket[-1] in ("A", "B", "C", "D")


# ---------------------------------------------------------------------------
# Scenario and case generation (deterministic with fixed seed)
# ---------------------------------------------------------------------------


class TestBuildScenarios:
    def test_returns_scenario_list(self):
        scenarios = build_scenarios(include=None, smoke=True, total_count=None)
        assert isinstance(scenarios, list)
        assert all(isinstance(s, Scenario) for s in scenarios)
        assert len(scenarios) >= 6  # At least 6 scenario types

    def test_each_scenario_has_required_fields(self):
        scenarios = build_scenarios(include=None, smoke=True, total_count=None)
        for s in scenarios:
            assert s.name
            assert s.platform
            assert s.scam_type
            assert s.count >= 1
            assert callable(s.generator)

    def test_include_filter(self):
        scenarios = build_scenarios(include=["romance_pretext"], smoke=True, total_count=None)
        assert len(scenarios) == 1
        assert scenarios[0].name == "romance_pretext"

    def test_total_count_distributes(self):
        scenarios = build_scenarios(include=None, smoke=False, total_count=16)
        total = sum(s.count for s in scenarios)
        assert total == 16


class TestBuildCases:
    def test_generates_correct_count(self):
        scenarios = build_scenarios(include=None, smoke=True, total_count=None)
        cases = build_cases(scenarios, seed=42)
        expected_count = sum(s.count for s in scenarios)
        assert len(cases) == expected_count

    def test_case_structure(self):
        scenarios = build_scenarios(include=["wallet_verification"], smoke=True, total_count=None)
        cases = build_cases(scenarios, seed=42)
        for case in cases:
            assert "id" in case
            assert "text" in case
            assert "summary" in case
            assert "entities" in case
            assert "dataset" in case

    def test_deterministic_with_same_seed(self):
        scenarios = build_scenarios(include=None, smoke=True, total_count=None)
        cases_a = build_cases(scenarios, seed=99)
        cases_b = build_cases(scenarios, seed=99)
        assert cases_a == cases_b


class TestBuildGroundTruth:
    def test_one_per_case(self):
        scenarios = build_scenarios(include=None, smoke=True, total_count=None)
        cases = build_cases(scenarios, seed=42)
        gt = build_ground_truth(cases, scenarios)
        assert len(gt) == len(cases)

    def test_ground_truth_fields(self):
        scenarios = build_scenarios(include=None, smoke=True, total_count=None)
        cases = build_cases(scenarios, seed=42)
        gt = build_ground_truth(cases, scenarios)
        for entry in gt:
            assert "id" in entry
            assert "tags" in entry
            assert "scam_type" in entry


class TestBuildSavedSearches:
    def test_returns_list(self):
        scenarios = build_scenarios(include=None, smoke=True, total_count=None)
        cases = build_cases(scenarios, seed=42)
        searches = build_saved_searches(cases, scenarios)
        assert isinstance(searches, list)
        assert len(searches) >= 1
        for s in searches:
            assert "name" in s
