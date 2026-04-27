"""Exhaustive unit tests for the damage parser (Sprint 2 Phase D)."""

from __future__ import annotations

from decimal import Decimal

from i4g.ingestion.phishdestroy.archive.damage import parse_deposit_messages

# ── Minimal valid message builders ────────────────────────────────────────────


def _ru_deposit(
    msg_id: int,
    amount: str = "$47.39",
    chain: str = "BTC",
    project: str = "GMB Casino",
) -> dict:
    """Build a valid Russian-language deposit message dict."""
    text = (
        f"📥 Зачислен новый депозит!\n"
        f"🎰 Проект: {project}\n"
        f"🀄️ Сеть: {chain}\n"
        f"👤 Воркер: Скрыт\n"
        f"💵 Сумма в USD: {amount}\n"
        f"📈 Процент: 55%\n"
        f"📂 К зачислению: $26.06\n"
    )
    return {"id": msg_id, "type": "message", "text": text}


def _en_deposit(
    msg_id: int,
    amount: str = "$99.00",
    chain: str = "ETH",
    project: str = "Spin Palace",
) -> dict:
    """Build a valid English-language deposit message dict."""
    text = (
        f"📥 New deposit received!\n"
        f"🎰 Project: {project}\n"
        f"🀄️ Network: {chain}\n"
        f"👤 Worker: Hidden\n"
        f"💵 Amount in USD: {amount}\n"
        f"📈 Percentage: 50%\n"
        f"📂 To be credited: $49.50\n"
    )
    return {"id": msg_id, "type": "message", "text": text}


def _service_msg(msg_id: int) -> dict:
    return {"id": msg_id, "type": "service", "text": "Joined the group"}


def _plain_msg(msg_id: int, text: str) -> dict:
    return {"id": msg_id, "type": "message", "text": text}


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestParseDepositMessagesBasic:
    def test_two_ru_one_en_returns_three_records(self) -> None:
        msgs = [
            _ru_deposit(1, "$47.39", "BTC", "GMB Casino"),
            _ru_deposit(2, "$1234.56", "ETH", "Casino X"),
            _en_deposit(3, "$99.00", "ETH", "Spin Palace"),
        ]
        records, skipped = parse_deposit_messages(msgs)
        assert len(records) == 3
        assert skipped == 0

    def test_russian_amounts_correct(self) -> None:
        msgs = [_ru_deposit(10, "$47.39", "BTC", "Proj")]
        records, _ = parse_deposit_messages(msgs)
        assert records[0].amount_usd_claimed == Decimal("47.39")
        assert records[0].chain == "BTC"
        assert records[0].project == "Proj"

    def test_english_amounts_correct(self) -> None:
        msgs = [_en_deposit(20, "$99.00", "ETH", "Spin Palace")]
        records, _ = parse_deposit_messages(msgs)
        assert records[0].amount_usd_claimed == Decimal("99.00")
        assert records[0].chain == "ETH"
        assert records[0].project == "Spin Palace"

    def test_message_id_preserved(self) -> None:
        msgs = [_ru_deposit(42)]
        records, _ = parse_deposit_messages(msgs)
        assert records[0].message_id == 42

    def test_credited_and_percent_parsed(self) -> None:
        msgs = [_ru_deposit(1, "$100.00")]
        records, _ = parse_deposit_messages(msgs)
        assert records[0].operator_share_percent == Decimal("55")
        assert records[0].amount_usd_credited == Decimal("26.06")


class TestParseDepositMessagesSkips:
    def test_service_type_skipped(self) -> None:
        msgs = [_service_msg(1), _ru_deposit(2)]
        records, skipped = parse_deposit_messages(msgs)
        assert len(records) == 1
        assert skipped == 1

    def test_message_without_deposit_header_skipped(self) -> None:
        msgs = [_plain_msg(5, "Hello world from admin"), _ru_deposit(6)]
        records, skipped = parse_deposit_messages(msgs)
        assert len(records) == 1
        assert skipped == 1

    def test_message_with_header_but_missing_amount_skipped(self) -> None:
        text = "📥 Зачислен новый депозит!\n🀄️ Сеть: BTC\n📈 Процент: 55%\n"
        msgs = [{"id": 7, "type": "message", "text": text}, _ru_deposit(8)]
        records, skipped = parse_deposit_messages(msgs)
        assert len(records) == 1
        assert skipped == 1

    def test_skipped_message_count_matches_fixture(self) -> None:
        msgs = [
            _ru_deposit(1),
            _ru_deposit(2),
            _en_deposit(3),
            _service_msg(4),
            _plain_msg(5, "Not a deposit message"),
        ]
        records, skipped = parse_deposit_messages(msgs)
        assert len(records) == 3
        assert skipped == 2


class TestParseDepositMessagesDecimalHandling:
    def test_comma_decimal_separator_parsed(self) -> None:
        """Amounts like '1 234,56' (comma decimal) must be parsed correctly."""
        text = "📥 Зачислен новый депозит!\n💵 Сумма в USD: $1234,56\n🀄️ Сеть: BTC\n"
        msgs = [{"id": 1, "type": "message", "text": text}]
        records, skipped = parse_deposit_messages(msgs)
        assert len(records) == 1
        assert records[0].amount_usd_claimed == Decimal("1234.56")
        assert skipped == 0

    def test_uses_decimal_not_float(self) -> None:
        msgs = [_ru_deposit(1, "$47.39")]
        records, _ = parse_deposit_messages(msgs)
        assert isinstance(records[0].amount_usd_claimed, Decimal)
        assert isinstance(records[0].amount_usd_credited, Decimal)
        assert isinstance(records[0].operator_share_percent, Decimal)


class TestParseDepositMessagesTextRendering:
    def test_text_entities_preferred(self) -> None:
        """When text_entities is present, it must be used instead of text field."""
        msg = {
            "id": 1,
            "type": "message",
            "text": "SHOULD NOT BE USED",
            "text_entities": [
                {"type": "plain", "text": "📥 Зачислен новый депозит!\n"},
                {"type": "plain", "text": "🀄️ Сеть: BTC\n"},
                {"type": "bold", "text": "💵 Сумма в USD: $55.00\n"},
            ],
        }
        records, skipped = parse_deposit_messages([msg])
        assert len(records) == 1
        assert records[0].amount_usd_claimed == Decimal("55.00")
        assert skipped == 0

    def test_list_of_objects_text_rendering(self) -> None:
        """text as list-of-objects must be joined correctly."""
        msg = {
            "id": 2,
            "type": "message",
            "text": [
                "📥 Зачислен новый депозит!\n",
                {"type": "bold", "text": "💵 Сумма в USD: $88.88\n"},
                "🀄️ Сеть: TRON\n",
            ],
        }
        records, skipped = parse_deposit_messages([msg])
        assert len(records) == 1
        assert records[0].amount_usd_claimed == Decimal("88.88")
        assert records[0].chain == "TRON"
        assert skipped == 0

    def test_chain_is_uppercased(self) -> None:
        msgs = [_ru_deposit(1, "$10.00", "tron")]
        records, _ = parse_deposit_messages(msgs)
        assert records[0].chain == "TRON"

    def test_raw_text_populated(self) -> None:
        msgs = [_ru_deposit(1)]
        records, _ = parse_deposit_messages(msgs)
        assert "Зачислен новый депозит" in records[0].raw_text


class TestParseDepositMessagesOptionalFields:
    def test_missing_chain_returns_none(self) -> None:
        text = "📥 Зачислен новый депозит!\n💵 Сумма в USD: $10.00\n"
        msgs = [{"id": 1, "type": "message", "text": text}]
        records, _ = parse_deposit_messages(msgs)
        assert records[0].chain is None

    def test_missing_project_returns_none(self) -> None:
        text = "📥 Зачислен новый депозит!\n💵 Сумма в USD: $10.00\n🀄️ Сеть: BTC\n"
        msgs = [{"id": 1, "type": "message", "text": text}]
        records, _ = parse_deposit_messages(msgs)
        assert records[0].project is None

    def test_missing_credited_returns_none(self) -> None:
        text = "📥 Зачислен новый депозит!\n💵 Сумма в USD: $10.00\n"
        msgs = [{"id": 1, "type": "message", "text": text}]
        records, _ = parse_deposit_messages(msgs)
        assert records[0].amount_usd_credited is None

    def test_missing_percent_returns_none(self) -> None:
        text = "📥 Зачислен новый депозит!\n💵 Сумма в USD: $10.00\n"
        msgs = [{"id": 1, "type": "message", "text": text}]
        records, _ = parse_deposit_messages(msgs)
        assert records[0].operator_share_percent is None

    def test_empty_messages_list(self) -> None:
        records, skipped = parse_deposit_messages([])
        assert records == []
        assert skipped == 0
