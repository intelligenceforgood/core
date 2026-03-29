"""Generate golden seed SQL for UI pages that need rich data.

Produces INSERT statements for:
  - threat_campaigns + threat_campaign_cases + campaign_stats  → intelligence/campaigns
  - infrastructure_edges                                        → intelligence/graph
  - review_queue + review_actions                               → intelligence/timeline
  - watchlist_items + watchlist_alerts                           → intelligence/watchlist
  - intake_records (diverse victim_country + loss_amount)        → impact/geography

Usage:
    python scripts/etl/synthesize_golden_data.py --output data/bundles/golden_seed/seed.sql

The output is pure SQL (INSERT … ON CONFLICT DO NOTHING) safe for both PostgreSQL and SQLite.
It references case_ids by a placeholder pattern; the build_golden_bundle script replaces
them with real ingested case_ids at consolidation time.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

UTC = UTC

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uuid() -> str:
    return str(uuid.uuid4())


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S+00")


def _json_lit(obj: object) -> str:
    """Escape a Python object as a SQL JSON literal (single-quote wrapped)."""
    return "'" + json.dumps(obj).replace("'", "''") + "'"


def _sql_text(value: str | None) -> str:
    if value is None:
        return "NULL"
    return "'" + value.replace("'", "''") + "'"


def _sql_num(value: float | int | None) -> str:
    if value is None:
        return "NULL"
    return str(value)


def _sql_bool(value: bool) -> str:
    return "true" if value else "false"


_NOW = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)

# ---------------------------------------------------------------------------
# Campaign definitions
# ---------------------------------------------------------------------------

CAMPAIGNS = [
    {
        "campaign_id": _uuid(),
        "name": "Romance Scam Ring — SE Asia",
        "description": "Coordinated romance/investment scam network operating from SE Asian compounds.",
        "status": "active",
        "risk_score": 87.5,
        "taxonomy_rollup": {"romance_scam": 0.6, "crypto_investment": 0.3, "pig_butchering": 0.1},
    },
    {
        "campaign_id": _uuid(),
        "name": "Crypto Investment Fraud — Telegram",
        "description": "Telegram-based crypto investment fraud targeting retail investors with fake yield farms.",
        "status": "active",
        "risk_score": 79.2,
        "taxonomy_rollup": {"crypto_investment": 0.8, "advance_fee": 0.2},
    },
    {
        "campaign_id": _uuid(),
        "name": "Tech Support Scam Network",
        "description": "Call-center driven tech support scam ring with remote-access trojans.",
        "status": "declining",
        "risk_score": 63.0,
        "taxonomy_rollup": {"tech_support_scam": 0.9, "remote_access": 0.1},
    },
    {
        "campaign_id": _uuid(),
        "name": "Advance Fee Fraud — 419",
        "description": "Classic 419 advance-fee fraud with modernized email templates.",
        "status": "active",
        "risk_score": 55.3,
        "taxonomy_rollup": {"advance_fee": 0.95, "impersonation": 0.05},
    },
    {
        "campaign_id": _uuid(),
        "name": "Pig Butchering — WhatsApp",
        "description": "WhatsApp-initiated pig butchering scheme using fake trading platforms.",
        "status": "emerging",
        "risk_score": 91.0,
        "taxonomy_rollup": {"pig_butchering": 0.7, "crypto_investment": 0.2, "romance_scam": 0.1},
    },
    {
        "campaign_id": _uuid(),
        "name": "Employment Scam — Remote Work",
        "description": "Fake remote job offers requiring upfront equipment purchases.",
        "status": "emerging",
        "risk_score": 44.8,
        "taxonomy_rollup": {"employment_scam": 0.85, "advance_fee": 0.15},
    },
    {
        "campaign_id": _uuid(),
        "name": "NFT Rug Pull Cluster",
        "description": "Series of connected NFT projects performing rug pulls after mint.",
        "status": "dormant",
        "risk_score": 72.1,
        "taxonomy_rollup": {"crypto_investment": 0.7, "rug_pull": 0.3},
    },
]

# ---------------------------------------------------------------------------
# Case placeholders — these will be linked to campaigns.
# The build_golden_bundle script replaces these with real case_ids.
# We generate deterministic placeholder IDs.
# ---------------------------------------------------------------------------

PLACEHOLDER_CASE_IDS = [f"golden-case-{i:04d}" for i in range(1, 41)]

# Map campaigns to case ranges
_CAMPAIGN_CASE_RANGES = [
    (0, slice(0, 8)),  # Romance — 8 cases
    (1, slice(8, 15)),  # Crypto Telegram — 7 cases
    (2, slice(15, 20)),  # Tech Support — 5 cases
    (3, slice(20, 25)),  # 419 — 5 cases
    (4, slice(25, 33)),  # Pig Butchering — 8 cases
    (5, slice(33, 36)),  # Employment — 3 cases
    (6, slice(36, 40)),  # NFT Rug Pull — 4 cases
]

# ---------------------------------------------------------------------------
# Entity + graph data
# ---------------------------------------------------------------------------

ENTITIES_FOR_GRAPH = [
    ("url", "stellar-bonds.co"),
    ("url", "stellar-finance.io"),
    ("url", "crypto-yield-farm.net"),
    ("url", "secure-wallet-verify.com"),
    ("url", "fastpay-global.org"),
    ("wallet_address", "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"),
    ("wallet_address", "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"),
    ("wallet_address", "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE"),
    ("email_address", "support@stellar-bonds.co"),
    ("email_address", "admin@crypto-yield-farm.net"),
    ("email_address", "helpdesk@fastpay-global.org"),
    ("phone_number", "+14155550127"),
    ("phone_number", "+852987650123"),
]

INFRASTRUCTURE_EDGES = [
    # domain ↔ domain (shared hosting)
    ("url", "stellar-bonds.co", "url", "stellar-finance.io", "shared_hosting", 0.95),
    ("url", "crypto-yield-farm.net", "url", "secure-wallet-verify.com", "shared_registrar", 0.88),
    ("url", "fastpay-global.org", "url", "stellar-bonds.co", "shared_ip", 0.72),
    # domain ↔ wallet
    ("url", "stellar-bonds.co", "wallet_address", "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh", "funds_flow", 0.90),
    (
        "url",
        "crypto-yield-farm.net",
        "wallet_address",
        "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "funds_flow",
        0.85,
    ),
    ("url", "stellar-finance.io", "wallet_address", "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE", "funds_flow", 0.80),
    # wallet ↔ wallet
    (
        "wallet_address",
        "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
        "wallet_address",
        "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "funds_flow",
        0.65,
    ),
    # email ↔ domain
    ("email_address", "support@stellar-bonds.co", "url", "stellar-bonds.co", "registration_email", 0.99),
    ("email_address", "admin@crypto-yield-farm.net", "url", "crypto-yield-farm.net", "registration_email", 0.99),
    ("email_address", "helpdesk@fastpay-global.org", "url", "fastpay-global.org", "registration_email", 0.97),
    # phone ↔ domain
    ("phone_number", "+14155550127", "url", "fastpay-global.org", "whois_phone", 0.82),
    ("phone_number", "+852987650123", "url", "stellar-finance.io", "whois_phone", 0.78),
    # cross-campaign email ↔ wallet
    (
        "email_address",
        "support@stellar-bonds.co",
        "wallet_address",
        "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE",
        "payment_instruction",
        0.70,
    ),
    # shared IP across campaigns
    ("url", "secure-wallet-verify.com", "url", "fastpay-global.org", "shared_ip", 0.60),
    ("url", "stellar-finance.io", "url", "crypto-yield-farm.net", "shared_nameserver", 0.55),
]

# ---------------------------------------------------------------------------
# Watchlist items
# ---------------------------------------------------------------------------

WATCHLIST_ITEMS = [
    (
        "wallet_address",
        "bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh",
        True,
        True,
        10000.0,
        "High-value BTC wallet linked to romance scam ring",
    ),
    (
        "wallet_address",
        "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        True,
        False,
        None,
        "ETH wallet — pig butchering payments",
    ),
    ("url", "stellar-bonds.co", True, False, None, "Primary scam domain — SE Asia romance ring"),
    ("url", "crypto-yield-farm.net", True, False, None, "Fake yield farm domain"),
    ("email_address", "support@stellar-bonds.co", True, False, None, "Scammer contact email"),
    ("phone_number", "+14155550127", True, False, None, "Contact number from multiple intakes"),
    ("wallet_address", "TQn9Y2khEsLJW1ChVWFMSMeRDow5KcbLSE", True, True, 5000.0, "TRON wallet — cross-campaign funds"),
    ("url", "fastpay-global.org", True, False, None, "Fake payment processor"),
]

# ---------------------------------------------------------------------------
# Intake records — diverse geography
# ---------------------------------------------------------------------------

INTAKE_RECORDS = [
    ("US", 45000.00, "USD", "Romance scam via dating app; victim transferred retirement funds"),
    ("US", 12000.00, "USD", "Crypto investment scam; victim used Coinbase to send BTC"),
    ("GB", 18500.00, "GBP", "Tech support scam; remote access led to unauthorized transfers"),
    ("AU", 32000.00, "AUD", "Pig butchering via WhatsApp; fake trading platform"),
    ("CA", 8900.00, "CAD", "Employment scam; paid for equipment that never arrived"),
    ("NG", 2500.00, "USD", "Advance fee fraud; promised government contract"),
    ("PH", 15000.00, "USD", "Romance scam; victim met suspect on Facebook"),
    ("SG", 48000.00, "SGD", "Crypto investment fraud via Telegram group"),
    ("DE", 22000.00, "EUR", "NFT rug pull; entire collection value lost"),
    ("JP", 3500000.00, "JPY", "Tech support scam targeting elderly victim"),
    ("IN", 850000.00, "INR", "Fake job offer requiring crypto payment"),
    ("BR", 45000.00, "BRL", "Romance scam via Instagram; victim sent funds via PIX"),
    ("ZA", 120000.00, "ZAR", "Investment scam; fake mining company shares"),
    ("KE", 380000.00, "KES", "Mobile money advance fee scam"),
    ("MX", 250000.00, "MXN", "Pig butchering; fake crypto exchange app"),
]

# ---------------------------------------------------------------------------
# SQL generation
# ---------------------------------------------------------------------------


def generate_sql() -> str:
    """Generate the complete golden seed SQL."""

    lines: list[str] = [
        "-- Golden Seed Data",
        "-- Generated by scripts/etl/synthesize_golden_data.py",
        f"-- Timestamp: {_ts(_NOW)}",
        "",
        "-- ===================================================================",
        "-- threat_campaigns",
        "-- ===================================================================",
        "",
    ]

    now = _ts(_NOW)

    for c in CAMPAIGNS:
        cols = (
            "campaign_id, name, description, origin, status, "
            "risk_score, taxonomy_rollup, created_by, created_at, updated_at"
        )
        lines.append(
            f"INSERT INTO threat_campaigns ({cols}) VALUES ("
            f"{_sql_text(c['campaign_id'])}, "
            f"{_sql_text(c['name'])}, "
            f"{_sql_text(c['description'])}, "
            f"'system', "
            f"{_sql_text(c['status'])}, "
            f"{_sql_num(c['risk_score'])}, "
            f"{_json_lit(c['taxonomy_rollup'])}, "
            f"'bootstrap', "
            f"'{now}', '{now}'"
            f") ON CONFLICT DO NOTHING;"
        )

    lines.extend(
        [
            "",
            "-- ===================================================================",
            "-- threat_campaign_cases",
            "-- ===================================================================",
            "",
        ]
    )

    for camp_idx, case_slice in _CAMPAIGN_CASE_RANGES:
        campaign = CAMPAIGNS[camp_idx]
        case_ids = PLACEHOLDER_CASE_IDS[case_slice]
        for cid in case_ids:
            lines.append(
                f"INSERT INTO threat_campaign_cases (campaign_id, case_id, linked_at, linked_by, link_reason) VALUES ("
                f"{_sql_text(campaign['campaign_id'])}, "
                f"{_sql_text(cid)}, "
                f"'{now}', 'bootstrap', 'Golden bundle seed linkage'"
                f") ON CONFLICT DO NOTHING;"
            )

    lines.extend(
        [
            "",
            "-- ===================================================================",
            "-- campaign_stats",
            "-- ===================================================================",
            "",
        ]
    )

    for camp_idx, case_slice in _CAMPAIGN_CASE_RANGES:
        campaign = CAMPAIGNS[camp_idx]
        n_cases = case_slice.stop - case_slice.start
        cols = (
            "campaign_id, case_count, indicator_count, loss_sum, victim_count, "
            "risk_score, taxonomy_rollup, status, first_case_at, last_case_at, "
            "entity_types, created_at, updated_at"
        )
        lines.append(
            f"INSERT INTO campaign_stats ({cols}) VALUES ("
            f"{_sql_text(campaign['campaign_id'])}, "
            f"{n_cases}, "
            f"{n_cases * 2}, "  # ~2 indicators per case
            f"{_sql_num(n_cases * 15000.0)}, "
            f"{n_cases}, "
            f"{_sql_num(campaign['risk_score'])}, "
            f"{_json_lit(campaign['taxonomy_rollup'])}, "
            f"{_sql_text(campaign['status'])}, "
            f"'{_ts(_NOW - timedelta(days=180))}', "
            f"'{now}', "
            f"{_json_lit(['wallet_address', 'url', 'email_address'])}, "
            f"'{now}', '{now}'"
            f") ON CONFLICT DO NOTHING;"
        )

    lines.extend(
        [
            "",
            "-- ===================================================================",
            "-- infrastructure_edges",
            "-- ===================================================================",
            "",
        ]
    )

    for src_type, src_val, tgt_type, tgt_val, edge_type, conf in INFRASTRUCTURE_EDGES:
        eid = _uuid()
        cols = (
            "edge_id, source_entity_type, source_canonical_value, "
            "target_entity_type, target_canonical_value, "
            "edge_type, confidence, discovered_at"
        )
        lines.append(
            f"INSERT INTO infrastructure_edges ({cols}) VALUES ("
            f"{_sql_text(eid)}, "
            f"{_sql_text(src_type)}, {_sql_text(src_val)}, "
            f"{_sql_text(tgt_type)}, {_sql_text(tgt_val)}, "
            f"{_sql_text(edge_type)}, {_sql_num(conf)}, "
            f"'{now}'"
            f") ON CONFLICT DO NOTHING;"
        )

    lines.extend(
        [
            "",
            "-- ===================================================================",
            "-- watchlist_items",
            "-- ===================================================================",
            "",
        ]
    )

    watchlist_ids: list[str] = []
    for etype, cval, alert_new, alert_loss, threshold, note in WATCHLIST_ITEMS:
        wid = _uuid()
        watchlist_ids.append(wid)
        cols = (
            "watchlist_id, entity_type, canonical_value, "
            "alert_on_new_case, alert_on_loss_increase, loss_threshold, "
            "note, created_by, created_at, updated_at"
        )
        lines.append(
            f"INSERT INTO watchlist_items ({cols}) VALUES ("
            f"{_sql_text(wid)}, "
            f"{_sql_text(etype)}, {_sql_text(cval)}, "
            f"{_sql_bool(alert_new)}, {_sql_bool(alert_loss)}, "
            f"{_sql_num(threshold)}, {_sql_text(note)}, "
            f"'bootstrap', '{now}', '{now}'"
            f") ON CONFLICT DO NOTHING;"
        )

    lines.extend(
        [
            "",
            "-- ===================================================================",
            "-- watchlist_alerts",
            "-- ===================================================================",
            "",
        ]
    )

    alert_messages = [
        ("new_case", "New case detected involving watched wallet bc1qxy2…"),
        ("new_case", "New case detected involving watched domain stellar-bonds.co"),
        ("loss_increase", "Total loss for bc1qxy2… exceeded $10,000 threshold"),
        ("new_case", "New case detected involving watched wallet 0x742d…"),
        ("new_case", "New case detected for email support@stellar-bonds.co"),
        ("new_case", "New case referencing phone +14155550127"),
        ("loss_increase", "Total loss for TQn9Y2… exceeded $5,000 threshold"),
        ("new_case", "New case detected involving crypto-yield-farm.net"),
        ("new_case", "New victim intake referencing stellar-bonds.co"),
        ("new_case", "Second case detected for wallet TQn9Y2…"),
        ("new_case", "Cross-campaign link detected: fastpay-global.org"),
        ("loss_increase", "Monthly loss increase: bc1qxy2… up 45% ($18,200 → $26,400)"),
        ("new_case", "New intake referencing watched phone +852987650123"),
        ("new_case", "New case involving employment scam with known wallet"),
        ("new_case", "NFT rug pull cluster: new case matches watched pattern"),
    ]

    for i, (atype, msg) in enumerate(alert_messages):
        aid = _uuid()
        # Cycle through watchlist items
        wid = watchlist_ids[i % len(watchlist_ids)]
        alert_time = _ts(_NOW - timedelta(hours=i * 8))
        lines.append(
            f"INSERT INTO watchlist_alerts (alert_id, watchlist_id, alert_type, message, is_read, created_at) VALUES ("
            f"{_sql_text(aid)}, "
            f"{_sql_text(wid)}, "
            f"{_sql_text(atype)}, {_sql_text(msg)}, "
            f"{_sql_bool(i < 5)}, "
            f"'{alert_time}'"
            f") ON CONFLICT DO NOTHING;"
        )

    lines.extend(
        [
            "",
            "-- ===================================================================",
            "-- review_queue + review_actions (timeline data)",
            "-- ===================================================================",
            "",
        ]
    )

    review_statuses = ["new", "in_review", "accepted", "rejected", "escalated"]
    action_types = ["status_change", "classify", "escalate", "assign", "note"]

    for i, cid in enumerate(PLACEHOLDER_CASE_IDS[:20]):
        rid = _uuid()
        status = review_statuses[i % len(review_statuses)]
        queued_at = _ts(_NOW - timedelta(days=180 - i * 9))
        lines.append(
            f"INSERT INTO review_queue (review_id, case_id, queued_at, priority, status) VALUES ("
            f"{_sql_text(rid)}, {_sql_text(cid)}, '{queued_at}', "
            f"{_sql_text('high' if i % 3 == 0 else 'medium')}, "
            f"{_sql_text(status)}"
            f") ON CONFLICT DO NOTHING;"
        )

        # 1-3 review actions per review item
        n_actions = (i % 3) + 1
        for j in range(n_actions):
            aid = _uuid()
            action = action_types[(i + j) % len(action_types)]
            action_at = _ts(_NOW - timedelta(days=180 - i * 9 - j))
            lines.append(
                f"INSERT INTO review_actions (action_id, review_id, actor, action, payload, created_at) VALUES ("
                f"{_sql_text(aid)}, {_sql_text(rid)}, 'analyst@example.com', "
                f"{_sql_text(action)}, "
                f"{_json_lit({'old_status': 'new', 'new_status': status})}, "
                f"'{action_at}'"
                f") ON CONFLICT DO NOTHING;"
            )

    lines.extend(
        [
            "",
            "-- ===================================================================",
            "-- intake_records (geographic diversity)",
            "-- ===================================================================",
            "",
        ]
    )

    for i, (country, loss, currency, summary) in enumerate(INTAKE_RECORDS):
        iid = _uuid()
        cid = PLACEHOLDER_CASE_IDS[i % len(PLACEHOLDER_CASE_IDS)]
        created = _ts(_NOW - timedelta(days=150 - i * 10))
        cols = (
            "intake_id, reporter_name, loss_amount, loss_currency, "
            "victim_country, summary, status, case_id, "
            "created_at, updated_at"
        )
        lines.append(
            f"INSERT INTO intake_records ({cols}) VALUES ("
            f"{_sql_text(iid)}, "
            f"'Anonymous Reporter', "
            f"{_sql_num(loss)}, {_sql_text(currency)}, {_sql_text(country)}, "
            f"{_sql_text(summary)}, "
            f"'processed', {_sql_text(cid)}, "
            f"'{created}', '{created}'"
            f") ON CONFLICT DO NOTHING;"
        )

    lines.extend(["", "-- Golden seed complete.", ""])
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Generate golden seed SQL")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/bundles/golden_seed/seed.sql"),
        help="Output SQL file path",
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    sql = generate_sql()
    args.output.write_text(sql, encoding="utf-8")
    print(f"✅ Generated golden seed SQL: {args.output} ({len(sql)} bytes)")


if __name__ == "__main__":
    main()
