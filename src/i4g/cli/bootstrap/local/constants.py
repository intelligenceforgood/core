"""Constants and default data for the local bootstrap workflow."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
SRC_DIR = ROOT / "src"
DATA_DIR = ROOT / "data"
BUNDLES_DIR = DATA_DIR / "bundles"
CHAT_SCREENS_DIR = DATA_DIR / "chat_screens"
OCR_OUTPUT = DATA_DIR / "ocr_output.jsonl"
SEMANTIC_OUTPUT = DATA_DIR / "entities_semantic.jsonl"
MANUAL_DEMO_DIR = DATA_DIR / "manual_demo"
CHROMA_DIR = DATA_DIR / "chroma_store"
SQLITE_DB = DATA_DIR / "i4g_store.db"
REPORTS_DIR = DATA_DIR / "reports" / "bootstrap_local"
PILOT_CASES_PATH = MANUAL_DEMO_DIR / "dossier_pilot_cases.json"

DEFAULT_PILOT_CASES = [
    {
        "case_id": "dossier-pilot-001",
        "text": (
            'Victim met "Alex" on social media, was convinced to move retirement savings into a sham'
            " staking pool and wired funds to an exchange wallet controlled by the actor."
        ),
        "classification": "romance_investment",
        "confidence": 0.93,
        "loss_amount_usd": 185000,
        "jurisdiction": "US-CA",
        "victim_country": "US",
        "offender_country": "NG",
        "accepted_at": "2025-11-28T18:45:00Z",
        "entities": {
            "emails": ["finance@stellar-bonds.co"],
            "crypto_wallets": ["bc1qxy2kgdygjrsqtzq2n0yrf2493p83kkfjhx0wlh"],
            "phone_numbers": ["+14155550127"],
        },
        "metadata": {
            "loss_currency": "USD",
            "intake_source": "northern-ca-fiu-2024Q4",
            "summary": "High-dollar romance funnel leveraging fake staking dashboards.",
        },
        "dataset": "dossier-pilot",
        "notes": "High priority given LEA interest in the rom-invest pattern.",
    },
    {
        "case_id": "dossier-pilot-002",
        "text": (
            "Shell merchant SwiftCart Pay intercepted ACH settlements and rerouted them through a"
            " US correspondent account before laundering via MX fintech partners."
        ),
        "classification": "merchant_fraud",
        "confidence": 0.9,
        "loss_amount_usd": 76000,
        "jurisdiction": "US-TX",
        "victim_country": "US",
        "offender_country": "MX",
        "accepted_at": "2025-11-30T14:20:00Z",
        "entities": {
            "bank_accounts": ["021000021-99118822"],
            "emails": ["support@swiftcart-pay.com"],
            "urls": ["https://swiftcart-pay.com/settlements"],
        },
        "metadata": {
            "loss_currency": "USD",
            "sector": "ecommerce",
            "summary": "Merchant impersonation with mule-controlled correspondent account.",
        },
        "dataset": "dossier-pilot",
        "notes": "Useful for showcasing ACH + mule indicators in a single dossier.",
    },
    {
        "case_id": "dossier-pilot-003",
        "text": (
            'Telegram pump group "Phoenix Quant" raised BTC from UK victims and disappeared after'
            " promising weekly 20% returns; funds moved through UAE OTC brokers."
        ),
        "classification": "crypto_rugpull",
        "confidence": 0.92,
        "loss_amount_usd": 310000,
        "jurisdiction": "GB-LND",
        "victim_country": "GB",
        "offender_country": "AE",
        "accepted_at": "2025-12-01T09:05:00Z",
        "entities": {
            "telegram_handles": ["@phoenix_quant"],
            "emails": ["ops@phoenixquant.ai"],
            "crypto_wallets": ["3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy"],
        },
        "metadata": {
            "loss_currency": "GBP",
            "summary": "Cross-border rug pull routed through UAE OTC brokers.",
            "intake_source": "uk-ncaa-2025W03",
        },
        "dataset": "dossier-pilot",
        "notes": "Demonstrates cross-border requirement hitting Europe to Gulf corridor.",
    },
]

__all__ = [
    "ROOT",
    "SRC_DIR",
    "DATA_DIR",
    "BUNDLES_DIR",
    "CHAT_SCREENS_DIR",
    "OCR_OUTPUT",
    "SEMANTIC_OUTPUT",
    "MANUAL_DEMO_DIR",
    "CHROMA_DIR",
    "SQLITE_DB",
    "REPORTS_DIR",
    "PILOT_CASES_PATH",
    "DEFAULT_PILOT_CASES",
]
