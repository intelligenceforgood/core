from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence

import yaml

ISO_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
DATASET_ID = "synthetic_coverage"


@dataclass
class Scenario:
    """Configuration for a synthetic scenario."""

    name: str
    platform: str
    scam_type: str
    base_tags: list[str]
    query: str
    count: int
    generator: Callable[[random.Random, int], dict[str, Any]]


@dataclass
class GenerationResult:
    """Summary of generated artifacts."""

    cases_path: Path
    ground_truth_path: Path
    vertex_docs_path: Path
    saved_searches_path: Path
    manifest_path: Path
    ocr_dir: Path
    case_count: int


def make_summary(text: str) -> str:
    snippet = text.strip().split(". ")[0]
    return snippet.strip()


def _rand_amount(min_value: float, max_value: float, rng: random.Random, precision: int = 2) -> float:
    return round(rng.uniform(min_value, max_value), precision)


def _rand_wallet(asset: str, rng: random.Random) -> str:
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


def _rand_phone(rng: random.Random) -> str:
    return f"+1-877-{rng.randint(100, 999)}-{rng.randint(1000, 9999)}"


def _rand_ticket(rng: random.Random) -> str:
    return f"TX-{rng.randint(100000, 999999)}-{rng.choice(['A', 'B', 'C', 'D'])}"


def wallet_verification(rng: random.Random, idx: int) -> dict[str, Any]:
    agent = rng.choice(["Anna", "Marcus", "Priya", "Linh", "Riley"])
    user = rng.choice(["Alex", "Taylor", "Jordan", "Reese"])
    provider = rng.choice(["Ledger Safety", "Coinbase Guard", "Binance Security"])
    asset = rng.choice(["USDT", "USDC", "ETH", "BTC"])
    wallet = _rand_wallet(asset, rng)
    amount = _rand_amount(75, 420, rng, 2)
    text = (
        f"Hi {user}, this is {agent} from {provider}. "
        f"We flagged a withdrawal attempt. To keep the account active, send {amount} {asset} to {wallet} "
        "within 15 minutes. Reply DONE once complete so we can secure your funds."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "people": [{"role": "agent", "value": agent}, {"role": "user", "value": user}],
            "organizations": [{"value": provider}],
            "wallet_addresses": [{"value": wallet}],
            "crypto_assets": [{"value": asset}],
        },
        "structured_fields": {
            "payment_method": "crypto_transfer",
            "asset": asset,
            "amount": amount,
            "deadline_minutes": 15,
        },
        "tags": [asset.lower(), "verification"],
        "fraud_confidence": "high",
    }


def romance_pretext(rng: random.Random, idx: int) -> dict[str, Any]:
    alias = rng.choice(["Sofia", "Diego", "Elena", "Mateo"])
    city = rng.choice(["Barcelona", "Lisbon", "Prague"])
    asset = rng.choice(["BTC", "USDT", "ETH"])
    wallet = _rand_wallet(asset, rng)
    amount = _rand_amount(180, 640, rng, 2)
    text = (
        f"My love, visa office in {city} needs proof of funds today. Please send {amount} {asset} to {wallet}. "
        "Once I land we will start our life together."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "people": [{"role": "alias", "value": alias}],
            "locations": [{"value": city}],
            "wallet_addresses": [{"value": wallet}],
            "crypto_assets": [{"value": asset}],
        },
        "structured_fields": {
            "payment_method": "crypto_transfer",
            "asset": asset,
            "amount": amount,
            "pretext": "immigration_fee",
        },
        "tags": ["romance", asset.lower()],
        "fraud_confidence": "high",
    }


def investment_signal_group(rng: random.Random, idx: int) -> dict[str, Any]:
    community = rng.choice(["Titan Yield", "Nova Chain", "Atlas Signal", "Velocity Room"])
    token = rng.choice(["SOLRIX", "LUMENX", "POLAR", "RADIANT"])
    analyst = rng.choice(["Mason", "Linh", "Camila"])
    entry = _rand_amount(0.08, 0.42, rng, 3)
    target = round(entry * rng.uniform(2.8, 4.5), 3)
    text = (
        f"Alert from {community}: analyst {analyst} confirmed liquidity on {token}. Buy at ${entry} and exit at "
        f"${target}. Post screenshot proof in the channel."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "organizations": [{"value": community}],
            "people": [{"role": "analyst", "value": analyst}],
            "tokens": [{"value": token}],
        },
        "structured_fields": {
            "payment_method": "crypto_exchange",
            "token": token,
            "entry_price_usd": entry,
            "target_price_usd": target,
        },
        "tags": [token.lower(), "pump"],
        "fraud_confidence": "medium",
    }


def tech_support_remote(rng: random.Random, idx: int) -> dict[str, Any]:
    brand = rng.choice(["Microsoft", "Apple", "Google", "Norton"])
    tool = rng.choice(["AnyDesk", "TeamViewer", "QuickAssist"])
    callback = _rand_phone(rng)
    ticket = _rand_ticket(rng)
    text = (
        f"{brand} Security Desk: ticket {ticket} shows license expired. Install {tool} and share the session code. "
        f"We will refund the $349 fee after remote review. Call {callback} now."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "organizations": [{"value": f"{brand} Security Desk"}],
            "software": [{"value": tool}],
            "ticket_ids": [{"value": ticket}],
            "phone_numbers": [{"value": callback}],
        },
        "structured_fields": {
            "payment_method": "gift_card_or_wire",
            "requires_remote_access": True,
            "callback_number": callback,
            "ticket_id": ticket,
        },
        "tags": [brand.lower(), tool.lower(), "tech-support"],
        "fraud_confidence": "high",
    }


def government_impostor_refund(rng: random.Random, idx: int) -> dict[str, Any]:
    agency = rng.choice(
        [
            "Internal Revenue Service",
            "Social Security Administration",
            "Department of Labor",
            "Australian Taxation Office",
        ]
    )
    retailer = rng.choice(["Amazon", "Target", "Apple Store"])
    amount = rng.randint(1200, 5200)
    transaction_id = _rand_ticket(rng)
    hotline = _rand_phone(rng)
    text = (
        f"{agency} notice: your {retailer} refund of ${amount} is on hold for compliance fees. "
        f"Settle today via bonds using case {transaction_id}. Hotline: {hotline}."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "agencies": [{"value": agency}],
            "retailers": [{"value": retailer}],
            "transaction_ids": [{"value": transaction_id}],
            "phone_numbers": [{"value": hotline}],
        },
        "structured_fields": {
            "payment_method": "prepaid_bonds",
            "fee_amount_usd": amount,
            "hotline": hotline,
            "case_reference": transaction_id,
        },
        "tags": [agency.lower().replace(" ", "-"), "refund"],
        "fraud_confidence": "medium",
    }


def gift_card_bec(rng: random.Random, idx: int) -> dict[str, Any]:
    exec_name = rng.choice(["Jon", "Riley", "Camila", "Fatima"])
    retailer = rng.choice(["Steam", "Apple", "Google Play", "Walmart"])
    quantity = rng.randint(3, 6)
    value = rng.choice([100, 200, 500])
    text = (
        f"Urgent: it's {exec_name} from leadership. Investor demo in 20 minutes and procurement failed. "
        f"Buy {quantity} {retailer} gift cards at ${value} each, scratch the codes, and text back photos."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "people": [{"role": "executive", "value": exec_name}],
            "retailers": [{"value": retailer}],
        },
        "structured_fields": {
            "payment_method": "gift_card_codes",
            "card_brand": retailer,
            "card_quantity": quantity,
            "card_value_usd": value,
        },
        "tags": [retailer.lower(), "gift-card", "bec"],
        "fraud_confidence": "high",
    }


def payment_handle_redirect(rng: random.Random, idx: int) -> dict[str, Any]:
    handle = rng.choice(["$secureteam", "@payfixhelp", "@zelle_auth", "@cashreview"])
    platform = rng.choice(["PayPal", "Cash App", "Zelle"])
    loss = _rand_amount(180, 880, rng, 2)
    text = (
        f"{platform} Safety: unusual transfer detected. To release ${loss}, DM payment handle {handle} with your "
        "reference code. Processing pauses in 10 minutes."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "handles": [{"platform": platform.lower(), "value": handle}],
        },
        "structured_fields": {
            "payment_method": "p2p_handle",
            "platform": platform,
            "handle": handle,
            "loss_amount_usd": loss,
        },
        "tags": [platform.lower(), "handle-redirect"],
        "fraud_confidence": "high",
    }


def bank_mule_redirect(rng: random.Random, idx: int) -> dict[str, Any]:
    bank = rng.choice(["Chase", "Bank of America", "Wells Fargo", "Citibank"])
    routing = rng.randint(21000000, 29999999)
    account = rng.randint(100120045, 999991242)
    contact = _rand_phone(rng)
    text = (
        f"{bank} Fraud Desk: inbound wire flagged as mule activity. Move funds to escrow account {account} routing "
        f"{routing} and call {contact} for clearance."
    )
    return {
        "text": text,
        "summary": make_summary(text),
        "entities": {
            "banks": [{"value": bank}],
            "routing_numbers": [{"value": str(routing)}],
            "account_numbers": [{"value": str(account)}],
            "phone_numbers": [{"value": contact}],
        },
        "structured_fields": {
            "payment_method": "wire_transfer",
            "routing_number": str(routing),
            "account_number": str(account),
            "callback_number": contact,
        },
        "tags": [bank.lower().replace(" ", "-"), "mule"],
        "fraud_confidence": "high",
    }


def build_scenarios(include: Optional[list[str]], smoke: bool, total_count: Optional[int]) -> list[Scenario]:
    base_count = 3 if smoke else 12
    scenarios: list[Scenario] = [
        Scenario(
            name="wallet_verification",
            platform="sms",
            scam_type="account_takeover",
            base_tags=["crypto", "account-security"],
            query="wallet verification crypto deposit scam",
            count=base_count,
            generator=wallet_verification,
        ),
        Scenario(
            name="romance_pretext",
            platform="sms",
            scam_type="romance",
            base_tags=["romance", "crypto"],
            query="romance bitcoin visa fee",
            count=base_count,
            generator=romance_pretext,
        ),
        Scenario(
            name="investment_signal_group",
            platform="chat",
            scam_type="investment",
            base_tags=["investment", "pump"],
            query="pump room token signal group",
            count=base_count,
            generator=investment_signal_group,
        ),
        Scenario(
            name="tech_support_remote",
            platform="phone",
            scam_type="tech_support_scam",
            base_tags=["tech-support", "remote-access"],
            query="license expired remote support refund",
            count=base_count,
            generator=tech_support_remote,
        ),
        Scenario(
            name="government_impostor_refund",
            platform="phone",
            scam_type="government_impostor",
            base_tags=["government", "refund"],
            query="government impostor refund bond payment",
            count=base_count,
            generator=government_impostor_refund,
        ),
        Scenario(
            name="gift_card_bec",
            platform="email",
            scam_type="business_email_compromise",
            base_tags=["bec", "gift-card"],
            query="gift card shakedown investor demo",
            count=base_count,
            generator=gift_card_bec,
        ),
        Scenario(
            name="payment_handle_redirect",
            platform="chat",
            scam_type="p2p_redirect",
            base_tags=["p2p", "handle"],
            query="cash app handle redirect",
            count=base_count,
            generator=payment_handle_redirect,
        ),
        Scenario(
            name="bank_mule_redirect",
            platform="phone",
            scam_type="mule_redirect",
            base_tags=["wire", "mule"],
            query="bank fraud desk mule redirect",
            count=base_count,
            generator=bank_mule_redirect,
        ),
    ]

    if include:
        include_set = set(include)
        scenarios = [scenario for scenario in scenarios if scenario.name in include_set]

    if total_count is not None and scenarios:
        per = max(total_count // len(scenarios), 1)
        remainder = max(total_count - per * len(scenarios), 0)
        for idx, scenario in enumerate(scenarios):
            scenario.count = per + (1 if idx < remainder else 0)

    return scenarios


def build_cases(scenarios: list[Scenario], seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    cases: list[dict[str, Any]] = []

    for scenario in scenarios:
        for idx in range(scenario.count):
            base = scenario.generator(rng, idx)
            case_id = f"{DATASET_ID}-{scenario.name}-{idx + 1:03d}"
            tags = sorted(set(scenario.base_tags + base.get("tags", [])))
            cases.append(
                {
                    "id": case_id,
                    "dataset": DATASET_ID,
                    "source": "synthetic",
                    "scenario": scenario.name,
                    "platform": scenario.platform,
                    "scam_type": scenario.scam_type,
                    "text": base["text"],
                    "summary": base["summary"],
                    "tags": tags,
                    "entities": base.get("entities", {}),
                    "structured_fields": base.get("structured_fields", {}),
                    "fraud_confidence": base.get("fraud_confidence", "medium"),
                }
            )

    return cases


def build_ground_truth(cases: list[dict[str, Any]], scenarios: list[Scenario]) -> list[dict[str, Any]]:
    scenario_queries = {scenario.name: scenario.query for scenario in scenarios}
    ground_truth: list[dict[str, Any]] = []
    for record in cases:
        scenario_name = record.get("scenario")
        ground_truth.append(
            {
                "id": record["id"],
                "query": scenario_queries.get(scenario_name, ""),
                "scam_type": record["scam_type"],
                "tags": record["tags"],
                "platform": record["platform"],
                "entities": record["entities"],
                "structured_fields": record["structured_fields"],
            }
        )
    return ground_truth


def build_vertex_docs(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    docs: list[dict[str, Any]] = []
    for record in cases:
        docs.append(
            {
                "id": record["id"],
                "content": {
                    "title": record["scam_type"].replace("_", " ").title(),
                    "body": record["text"],
                },
                "structData": {
                    "dataset": record["dataset"],
                    "scam_type": record["scam_type"],
                    "platform": record["platform"],
                    "tags": record["tags"],
                    "entities": record["entities"],
                    "structured_fields": record["structured_fields"],
                },
            }
        )
    return docs


def build_saved_searches(cases: list[dict[str, Any]], scenarios: list[Scenario]) -> list[dict[str, Any]]:
    first_case_by_scenario: dict[str, dict[str, Any]] = {}
    for case in cases:
        scenario_key = case.get("scenario")
        if scenario_key and scenario_key not in first_case_by_scenario:
            first_case_by_scenario[scenario_key] = case

    saved_searches: list[dict[str, Any]] = []
    for scenario in scenarios:
        sample_case = first_case_by_scenario.get(scenario.name)
        entity_filters: list[dict[str, Any]] = []
        if sample_case and sample_case.get("entities"):
            for entity_type, values in sample_case["entities"].items():
                if values:
                    entity_value = values[0].get("value") or values[0]
                    if isinstance(entity_value, str):
                        entity_filters.append(
                            {
                                "type": entity_type,
                                "value": entity_value,
                                "match_mode": "contains",
                            }
                        )
                    break

        saved_searches.append(
            {
                "name": f"Synthetic {scenario.scam_type}",
                "params": {
                    "text": scenario.query,
                    "datasets": [DATASET_ID],
                    "classifications": [scenario.scam_type],
                    "saved_search_tags": ["synthetic", "coverage"],
                    "entities": entity_filters,
                },
                "tags": ["synthetic", "coverage", scenario.name],
                "favorite": False,
            }
        )

    return saved_searches


def write_jsonl(records: Iterable[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record) + "\n")


def write_yaml(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(records, sort_keys=False, allow_unicode=False), encoding="utf-8")


def write_json(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_ocr_samples(cases: list[dict[str, Any]], output_dir: Path, limit: int = 5) -> Path:
    ocr_dir = output_dir / "ocr_samples"
    ocr_dir.mkdir(parents=True, exist_ok=True)
    for idx, record in enumerate(cases[:limit]):
        (ocr_dir / f"ocr_{idx + 1:03d}.txt").write_text(record["text"], encoding="utf-8")
    return ocr_dir


def write_manifest(
    output_dir: Path,
    cases_path: Path,
    ground_truth_path: Path,
    vertex_docs_path: Path,
    saved_searches_path: Path,
    ocr_dir: Path,
    seed: int,
    smoke: bool,
    case_count: int,
    saved_search_count: int,
    scenario_count: int,
) -> Path:
    ocr_files = sorted(ocr_dir.glob("*.txt"))
    manifest = {
        "bundle": DATASET_ID,
        "generated_at": datetime.utcnow().strftime(ISO_FORMAT),
        "seed": seed,
        "smoke": smoke,
        "case_count": case_count,
        "scenario_count": scenario_count,
        "saved_search_count": saved_search_count,
        "files": {
            "cases_jsonl": {
                "path": str(cases_path),
                "sha256": file_sha256(cases_path),
                "count": case_count,
            },
            "ground_truth": {
                "path": str(ground_truth_path),
                "sha256": file_sha256(ground_truth_path),
                "count": case_count,
            },
            "vertex_docs": {
                "path": str(vertex_docs_path),
                "sha256": file_sha256(vertex_docs_path),
                "count": case_count,
            },
            "saved_searches": {
                "path": str(saved_searches_path),
                "sha256": file_sha256(saved_searches_path),
                "count": saved_search_count,
            },
            "ocr_samples": {
                "path": str(ocr_dir),
                "files": [str(path) for path in ocr_files],
                "count": len(ocr_files),
            },
        },
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def generate_bundle(
    output_dir: Path = Path("data/bundles/synthetic_coverage"),
    seed: int = 1337,
    include: Optional[list[str]] = None,
    smoke: bool = False,
    total_count: Optional[int] = None,
) -> GenerationResult:
    scenarios = build_scenarios(include=include, smoke=smoke, total_count=total_count)
    cases = build_cases(scenarios, seed)
    ground_truth = build_ground_truth(cases, scenarios)
    vertex_docs = build_vertex_docs(cases)
    saved_searches = build_saved_searches(cases, scenarios)

    cases_path = output_dir / "cases.jsonl"
    ground_truth_path = output_dir / "ground_truth.yaml"
    vertex_docs_path = output_dir / "vertex_docs.jsonl"
    saved_searches_path = output_dir / "saved_searches.json"

    write_jsonl(cases, cases_path)
    write_yaml(ground_truth, ground_truth_path)
    write_jsonl(vertex_docs, vertex_docs_path)
    write_json(saved_searches, saved_searches_path)
    ocr_dir = write_ocr_samples(cases, output_dir)

    manifest_path = write_manifest(
        output_dir,
        cases_path,
        ground_truth_path,
        vertex_docs_path,
        saved_searches_path,
        ocr_dir,
        seed,
        smoke,
        len(cases),
        len(saved_searches),
        len(scenarios),
    )

    return GenerationResult(
        cases_path=cases_path,
        ground_truth_path=ground_truth_path,
        vertex_docs_path=vertex_docs_path,
        saved_searches_path=saved_searches_path,
        manifest_path=manifest_path,
        ocr_dir=ocr_dir,
        case_count=len(cases),
    )


def main(argv: Sequence[str] | None = None) -> int:
    # Minimal argparse avoided to keep Typer as the primary interface; support direct invocation with defaults.
    _ = argv  # Unused; retained for signature compatibility.
    result = generate_bundle()
    print("Generated synthetic coverage bundle at %s (cases=%d)" % (result.manifest_path.parent, result.case_count))
    return 0


__all__ = [
    "GenerationResult",
    "generate_bundle",
    "build_cases",
    "build_ground_truth",
    "build_vertex_docs",
    "build_saved_searches",
    "build_scenarios",
]
