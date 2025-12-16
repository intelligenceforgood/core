"""Generate synthetic retrieval evaluation datasets (moved from scripts/prepare_retrieval_dataset.py)."""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Sequence

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

AGENT_NAMES = [
    "Anna",
    "Marcus",
    "Linh",
    "Priya",
    "Stefan",
    "Riley",
    "Wei",
    "Camila",
    "Jon",
    "Fatima",
]

VICTIM_NAMES = [
    "Alex",
    "Jordan",
    "Taylor",
    "Morgan",
    "Casey",
    "Avery",
    "Emerson",
    "Reese",
    "Dakota",
    "Skyler",
]

WALLET_PROVIDERS = [
    "TrustWallet Security",
    "Ledger Support Desk",
    "Kraken Account Review",
    "Coinbase Safety Team",
    "Binance Wallet Guard",
]

ROMANCE_ALIASES = [
    "Sofia",
    "Luka",
    "Isabella",
    "Mateo",
    "Elena",
    "Noah",
    "Maya",
    "Diego",
]

ROMANCE_CITIES = [
    "Barcelona",
    "Lisbon",
    "Prague",
    "Buenos Aires",
    "Copenhagen",
]

INVEST_COMMUNITIES = [
    "Phoenix Alpha Circle",
    "Titan Yield Syndicate",
    "Atlas Signal Hub",
    "Nova Chain Collective",
    "Velocity Crypto Room",
]

EMERGING_TOKENS = [
    "SOLRIX",
    "LUMENX",
    "POLAR",
    "RADIANT",
    "NEONIA",
]

TECH_SUPPORT_BRANDS = [
    "Microsoft",
    "Apple",
    "Google",
    "Norton",
    "McAfee",
]

REMOTE_TOOLS = [
    "AnyDesk",
    "TeamViewer",
    "QuickAssist",
    "UltraViewer",
]

IMPOSTOR_AGENCIES = [
    "Internal Revenue Service",
    "Social Security Administration",
    "Department of Labor",
    "HM Revenue & Customs",
    "Australian Taxation Office",
]

RETAILERS = [
    "Amazon",
    "BestBuy",
    "Target",
    "Walmart",
    "Apple Store",
]

GIFT_CARD_BRANDS = [
    "Amazon",
    "Steam",
    "Apple",
    "Google Play",
    "Walmart",
]

CRYPTO_ASSETS = ["USDT", "USDC", "BTC", "ETH", "SOL"]


@dataclass
class TemplateConfig:
    label: str
    category: str
    channel: str
    count: int
    query: str
    notes: str
    tags: List[str]
    keywords: List[str]
    generator: Callable[["TemplateConfig", int, random.Random], Dict[str, object]]


def random_wallet(asset: str, rng: random.Random) -> str:
    if asset == "BTC":
        prefix = rng.choice(["1", "3", "bc1"])
        body = "".join(rng.choices("0123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz", k=30))
        return f"{prefix}{body}"
    if asset in {"USDT", "USDC", "ETH"}:
        body = "".join(rng.choices("0123456789abcdef", k=40))
        return f"0x{body}"
    if asset == "SOL":
        body = "".join(rng.choices("0123456789ABCDEFGHJKLMNPQRSTUVWXYZ", k=32))
        return body
    body = "".join(rng.choices("0123456789ABCDEF", k=32))
    return body


def random_amount(asset: str, rng: random.Random) -> float:
    if asset in {"USDT", "USDC"}:
        return round(rng.uniform(80, 450), 2)
    if asset == "BTC":
        return round(rng.uniform(0.015, 0.18), 5)
    if asset == "ETH":
        return round(rng.uniform(0.25, 4.0), 3)
    if asset == "SOL":
        return round(rng.uniform(5, 40), 2)
    return round(rng.uniform(100, 800), 2)


def make_summary(text: str) -> str:
    snippet = text.strip().split(". ")[0]
    return snippet.strip()


def iso_timestamp(offset_days: int, rng: random.Random) -> str:
    now = datetime.utcnow() - timedelta(days=offset_days)
    shifted = now - timedelta(hours=rng.randint(0, 23), minutes=rng.randint(0, 59))
    return shifted.strftime(ISO_FORMAT)


def wallet_verification_generator(cfg: TemplateConfig, idx: int, rng: random.Random) -> Dict[str, object]:
    agent = rng.choice(AGENT_NAMES)
    user = rng.choice(VICTIM_NAMES)
    provider = rng.choice(WALLET_PROVIDERS)
    asset = rng.choice(CRYPTO_ASSETS)
    amount = random_amount(asset, rng)
    wallet = random_wallet(asset, rng)
    text = (
        f"Hi {user}, this is {agent} from {provider}. "
        f"We flagged a withdrawal attempt on your wallet. To keep the account active, "
        f"send a verification deposit of {amount} {asset} to {wallet} in the next 15 minutes. "
        "Reply DONE once complete so we can secure your funds."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "people": [{"role": "agent", "value": agent}] + [{"role": "user", "value": user}],
            "organizations": [{"value": provider}],
            "crypto_assets": [{"value": asset}],
            "wallet_addresses": [{"value": wallet}],
        },
        "tags": cfg.tags + [asset.lower(), "verification"],
        "risk_level": "high",
        "structured_fields": {
            "payment_method": "crypto_transfer",
            "asset": asset,
            "amount": amount,
            "deadline_minutes": 15,
        },
    }


def romance_bitcoin_generator(cfg: TemplateConfig, idx: int, rng: random.Random) -> Dict[str, object]:
    alias = rng.choice(ROMANCE_ALIASES)
    user = rng.choice(VICTIM_NAMES)
    city = rng.choice(ROMANCE_CITIES)
    asset = rng.choice(["BTC", "USDT", "ETH"])
    amount = random_amount(asset, rng)
    wallet = random_wallet(asset, rng)
    text = (
        f"My love {user}, the visa office in {city} finally approved us but I must show proof of funds today. "
        f"Please send {amount} {asset} to {wallet}. Once I land we will start our life together. "
        "I am counting every minute until we meet."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "people": [{"role": "alias", "value": alias}, {"role": "user", "value": user}],
            "locations": [{"value": city}],
            "crypto_assets": [{"value": asset}],
            "wallet_addresses": [{"value": wallet}],
        },
        "tags": cfg.tags + ["romance", asset.lower()],
        "risk_level": "high",
        "structured_fields": {
            "payment_method": "crypto_transfer",
            "asset": asset,
            "amount": amount,
            "pretext": "immigration_fee",
        },
    }


def investment_group_generator(cfg: TemplateConfig, idx: int, rng: random.Random) -> Dict[str, object]:
    community = rng.choice(INVEST_COMMUNITIES)
    token = rng.choice(EMERGING_TOKENS)
    analyst = rng.choice(AGENT_NAMES)
    entry_price = round(rng.uniform(0.08, 0.42), 3)
    target = round(entry_price * rng.uniform(2.5, 4.8), 3)
    text = (
        f"Alert from {community}! Analyst {analyst} confirmed liquidity injection on {token}. "
        f"Buy at ${entry_price} before 21:30 UTC and flip when it hits ${target}. "
        "Screenshots required in chat to verify your position."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "organizations": [{"value": community}],
            "people": [{"role": "analyst", "value": analyst}],
            "tokens": [{"value": token}],
        },
        "tags": cfg.tags + [token.lower(), "pump"],
        "risk_level": "medium",
        "structured_fields": {
            "payment_method": "crypto_exchange",
            "token": token,
            "entry_price_usd": entry_price,
            "target_price_usd": target,
            "channel_requirements": "screenshot_verification",
        },
    }


def tech_support_generator(cfg: TemplateConfig, idx: int, rng: random.Random) -> Dict[str, object]:
    brand = rng.choice(TECH_SUPPORT_BRANDS)
    tool = rng.choice(REMOTE_TOOLS)
    ticket_id = f"{rng.randint(100000, 999999)}-{chr(rng.randint(65, 90))}"
    callback = f"+1-888-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"
    text = (
        f"{brand} Security Desk: ticket {ticket_id} shows your license expired. "
        f"Install {tool} and share the session code. Once connected we will refund the $349 fee, "
        f"but you must stay on the line. Call {callback} now."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "organizations": [{"value": f"{brand} Security Desk"}],
            "software": [{"value": tool}],
            "ticket_ids": [{"value": ticket_id}],
            "phone_numbers": [{"value": callback}],
        },
        "tags": cfg.tags + [brand.lower(), tool.lower()],
        "risk_level": "high",
        "structured_fields": {
            "payment_method": "gift_card_or_wire",
            "fee_amount_usd": 349,
            "requires_remote_access": True,
            "callback_number": callback,
        },
    }


def impostor_refund_generator(cfg: TemplateConfig, idx: int, rng: random.Random) -> Dict[str, object]:
    agency = rng.choice(IMPOSTOR_AGENCIES)
    retailer = rng.choice(RETAILERS)
    amount = rng.randint(1200, 5400)
    transaction_id = f"TX-{rng.randint(100000, 999999)}"
    text = (
        f"{agency} automated notice: your {retailer} refund of ${amount} was returned due to unpaid compliance fees. "
        f"Settle the balance today via government bonds or the levy increases. Reference case {transaction_id} when calling the hotline."
    )
    hotline = f"+1-877-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "agencies": [{"value": agency}],
            "retailers": [{"value": retailer}],
            "transaction_ids": [{"value": transaction_id}],
            "phone_numbers": [{"value": hotline}],
        },
        "tags": cfg.tags + [agency.lower().replace(" ", "-"), "refund"],
        "risk_level": "medium",
        "structured_fields": {
            "payment_method": "prepaid_bonds",
            "fee_amount_usd": amount,
            "hotline": hotline,
            "case_reference": transaction_id,
        },
    }


def gift_card_shakedown_generator(cfg: TemplateConfig, idx: int, rng: random.Random) -> Dict[str, object]:
    executive = rng.choice(AGENT_NAMES)
    user = rng.choice(VICTIM_NAMES)
    retailer = rng.choice(GIFT_CARD_BRANDS)
    quantity = rng.randint(3, 6)
    value = rng.choice([100, 200, 500])
    text = (
        f"Urgent: it's {executive} from the leadership team. Our investor demo starts in 20 minutes and "
        f"procurement failed to secure the {retailer} gift cards. Buy {quantity} cards worth ${value} each right now, "
        "scratch the codes, and text back photos. We will reimburse you immediately."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "people": [{"role": "executive", "value": executive}, {"role": "user", "value": user}],
            "retailers": [{"value": retailer}],
        },
        "tags": cfg.tags + [retailer.lower(), "gift-card"],
        "risk_level": "high",
        "structured_fields": {
            "payment_method": "gift_card_codes",
            "card_brand": retailer,
            "card_quantity": quantity,
            "card_value_usd": value,
        },
    }


TEMPLATE_GENERATORS: Dict[str, Callable[[TemplateConfig, int, random.Random], Dict[str, object]]] = {
    "wallet_verification": wallet_verification_generator,
    "romance_bitcoin": romance_bitcoin_generator,
    "investment_group": investment_group_generator,
    "tech_support": tech_support_generator,
    "impostor_refund": impostor_refund_generator,
    "gift_card_shakedown": gift_card_shakedown_generator,
}

DEFAULT_TEMPLATE_SPECS = [
    {
        "label": "wallet_verification",
        "category": "account_takeover",
        "channel": "sms",
        "count": 40,
        "query": "wallet verification crypto deposit scam",
        "notes": "SMS/IM messages demanding a crypto verification payment to keep an account active.",
        "tags": ["crypto", "account-security", "sms"],
        "keywords": ["wallet verification", "suspicious withdrawal", "send crypto"],
        "generator": "wallet_verification",
    },
    {
        "label": "romance_bitcoin",
        "category": "romance",
        "channel": "sms",
        "count": 40,
        "query": "romance bitcoin",
        "notes": "Romance scams demanding BTC/USDT to clear visas or emergencies.",
        "tags": ["romance", "crypto", "sms"],
        "keywords": ["immigration fee", "visa", "bitcoin"],
        "generator": "romance_bitcoin",
    },
    {
        "label": "investment_group",
        "category": "investment",
        "channel": "chat",
        "count": 40,
        "query": "pump room",
        "notes": "Coordinated pump-and-dump chat rooms.",
        "tags": ["investment", "pump"],
        "keywords": ["liquidity injection", "pump", "token"],
        "generator": "investment_group",
    },
    {
        "label": "tech_support",
        "category": "tech_support_scam",
        "channel": "phone",
        "count": 40,
        "query": "license expired",
        "notes": "Tech support scammers pushing remote tools.",
        "tags": ["tech_support_scam", "phone"],
        "keywords": ["license expired", "teamviewer", "refund"],
        "generator": "tech_support",
    },
    {
        "label": "impostor_refund",
        "category": "government_impostor",
        "channel": "phone",
        "count": 40,
        "query": "refund call",
        "notes": "Government impostor refund scams.",
        "tags": ["government", "impostor", "phone"],
        "keywords": ["refund", "compliance fee", "bonds"],
        "generator": "impostor_refund",
    },
    {
        "label": "gift_card_shakedown",
        "category": "business_email_compromise",
        "channel": "email",
        "count": 40,
        "query": "gift card",
        "notes": "BEC-style gift card shakedowns.",
        "tags": ["gift-card", "bec", "email"],
        "keywords": ["gift card", "investor demo", "reimburse"],
        "generator": "gift_card_shakedown",
    },
]


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed",
        type=int,
        default=1337,
        help="Random seed (default: 1337)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Total number of cases to generate (evenly split across templates unless include-templates is set).",
    )
    parser.add_argument(
        "--include-templates",
        nargs="+",
        default=None,
        help="Limit to specific templates by label.",
    )
    parser.add_argument(
        "--template-config",
        type=Path,
        default=None,
        help="Path to a JSON file containing template specs.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/retrieval_poc"),
        help="Destination directory for generated files.",
    )
    parser.add_argument(
        "--case-file",
        type=str,
        default="cases.jsonl",
        help="Filename for the cases JSONL output (relative to output-dir).",
    )
    parser.add_argument(
        "--ground-truth",
        type=str,
        default="ground_truth.yaml",
        help="Filename for the ground truth YAML output (relative to output-dir).",
    )
    parser.add_argument(
        "--manifest",
        type=str,
        default="manifest.json",
        help="Filename for the manifest JSON output (relative to output-dir).",
    )
    return parser


def load_template_specs(template_config: Path | None) -> list[dict[str, Any]]:
    if template_config is None:
        return DEFAULT_TEMPLATE_SPECS
    data = json.loads(template_config.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Template config must be a list of objects")
    return data


def build_templates(specs: list[dict[str, Any]]) -> list[TemplateConfig]:
    templates: list[TemplateConfig] = []
    for spec in specs:
        generator_name = spec.get("generator")
        generator = TEMPLATE_GENERATORS.get(generator_name)
        if generator is None:
            raise ValueError(f"Unknown generator '{generator_name}' in template spec")
        templates.append(
            TemplateConfig(
                label=spec["label"],
                category=spec["category"],
                channel=spec["channel"],
                count=int(spec["count"]),
                query=spec["query"],
                notes=spec.get("notes", ""),
                tags=list(spec.get("tags", [])),
                keywords=list(spec.get("keywords", [])),
                generator=generator,
            )
        )
    return templates


def generate_cases(
    templates: list[TemplateConfig], total_count: int | None, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(seed)

    if total_count is not None:
        # even distribution across templates
        per_template = max(total_count // len(templates), 1)
        for template in templates:
            template.count = per_template

    cases: list[dict[str, Any]] = []
    ground_truth: list[dict[str, Any]] = []

    for template in templates:
        for idx in range(template.count):
            case_id = f"case-{template.label}-{idx + 1:03d}"
            record = template.generator(template, idx, rng)
            record.update(
                {
                    "id": case_id,
                    "label": template.label,
                    "category": template.category,
                    "channel": template.channel,
                    "keywords": template.keywords,
                }
            )
            cases.append(record)
            ground_truth.append(
                {
                    "query": template.query,
                    "expected_ids": [case_id],
                    "expected_labels": [template.label],
                    "filter_expression": None,
                }
            )

    return cases, ground_truth


def write_outputs(
    cases: list[dict[str, Any]],
    ground_truth: list[dict[str, Any]],
    output_dir: Path,
    case_file: str,
    ground_truth_file: str,
    manifest_file: str,
    seed: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    case_path = output_dir / case_file
    with case_path.open("w", encoding="utf-8") as f:
        for record in cases:
            f.write(json.dumps(record) + "\n")

    import yaml

    gt_path = output_dir / ground_truth_file
    gt_path.write_text(
        yaml.safe_dump(ground_truth, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )

    manifest = {
        "generated_at": datetime.utcnow().strftime(ISO_FORMAT),
        "seed": seed,
        "case_file": str(case_path),
        "ground_truth_file": str(gt_path),
        "case_count": len(cases),
    }
    (output_dir / manifest_file).write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def generate_dataset(args: argparse.Namespace) -> int:
    specs = load_template_specs(args.template_config)
    templates = build_templates(specs)

    if args.include_templates:
        include = set(args.include_templates)
        templates = [t for t in templates if t.label in include]
        if not templates:
            raise SystemExit("No templates match the provided include list.")

    cases, ground_truth = generate_cases(templates, args.count, args.seed)
    write_outputs(cases, ground_truth, args.output_dir, args.case_file, args.ground_truth, args.manifest, args.seed)
    print(f"✅ Generated {len(cases)} cases to {args.output_dir}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    return generate_dataset(args)


__all__ = ["main", "generate_dataset"]
