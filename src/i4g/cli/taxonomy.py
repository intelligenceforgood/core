import typer
import yaml
import json
from pathlib import Path
from typing import Any

taxonomy_app = typer.Typer(help="Manage fraud taxonomy definitions and code generation.")

# Paths
# core/src/i4g/cli/taxonomy.py -> core/src/i4g/cli -> core/src/i4g -> core/src -> core
CORE_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = CORE_ROOT.parent
DEFINITIONS_PATH = CORE_ROOT / "src/i4g/taxonomy/definitions.yaml"
PYTHON_ENUMS_PATH = CORE_ROOT / "src/i4g/taxonomy/enums.py"
PYTHON_DATA_PATH = CORE_ROOT / "src/i4g/taxonomy/data.py"
TS_ENUMS_PATH = WORKSPACE_ROOT / "ui/packages/types/src/taxonomy.ts"
DOCS_PATH = WORKSPACE_ROOT / "docs/book/api/taxonomy_reference.md"


def load_definitions() -> dict[str, Any]:
    with open(DEFINITIONS_PATH) as f:
        return yaml.safe_load(f)


def generate_python_enums(data: dict[str, Any]):
    """
    Generate Python Enums for backend type safety.
    NOTE: These are still used by i4g.taxonomy.models for validation, even if the frontend fetches data dynamically.
    """
    lines = [
        '"""',
        "Fraud Taxonomy Enums",
        f'Version: fraud-taxonomy.v{data["version"]}',
        "",
        "Auto-generated from definitions.yaml. DO NOT EDIT.",
        '"""',
        "",
        "from enum import Enum",
        "",
    ]

    # Helper to generate an enum class
    def add_enum(class_name: str, items: list[dict[str, str]]):
        lines.append(f"class {class_name}(str, Enum):")
        for item in items:
            # Generate docstring for the enum member if description exists
            lines.append(f'    # {item["description"]}')
            # Key is the part after the dot, e.g. INTENT.IMPOSTER -> IMPOSTER
            key = item["code"].split(".")[-1]
            lines.append(f'    {key} = "{item["code"]}"')
        lines.append("")

    add_enum("ScamIntent", data["intents"])
    add_enum("DeliveryChannel", data["channels"])
    add_enum("SocialEngineeringTechnique", data["techniques"])
    add_enum("RequestedAction", data["actions"])
    add_enum("ClaimedPersona", data["personas"])

    with open(PYTHON_ENUMS_PATH, "w") as f:
        f.write("\n".join(lines))
    typer.echo(f"Generated {PYTHON_ENUMS_PATH}")


def generate_taxonomy_data(data: dict[str, Any]):
    """
    Generates the static data.py file which powers the API.
    Transforms the flat definitions.yaml lists into the axes-based structure.
    """
    import datetime

    # Axis metadata map
    axis_meta = {
        "intents": {"label": "Scam Intents", "description": "The primary goal or nature of the fraud."},
        "channels": {"label": "Delivery Channels", "description": "The method or platform used to contact the victim."},
        "techniques": {
            "label": "Social Engineering Techniques",
            "description": "The psychological manipulation methods used.",
        },
        "actions": {"label": "Requested Actions", "description": "What the fraudster asks the victim to do."},
        "personas": {"label": "Claimed Personas", "description": "Who the fraudster claims to be."},
    }

    axes = []
    for key, meta in axis_meta.items():
        if key in data:
            axes.append({"id": key, "label": meta["label"], "description": meta["description"], "items": data[key]})

    # Construct the final dictionary
    output_data = {
        "version": data.get("version", "1.0"),
        "steward": "Policy & Standards Team",
        "updatedAt": datetime.datetime.now(datetime.UTC).isoformat() + "Z",
        "axes": axes,
    }

    # Build flat code-to-label lookup map
    label_map: dict[str, str] = {}
    for key in ("intents", "channels", "techniques", "actions", "personas"):
        for item in data.get(key, []):
            label_map[item["code"]] = item["label"]

    lines = [
        '"""Static taxonomy data."""',
        "",
        "from typing import Any, Dict",
        "",
        f"TAXONOMY_DEFINITIONS: Dict[str, Any] = {json.dumps(output_data, indent=4)}",
        "",
        f"CODE_TO_LABEL: Dict[str, str] = {json.dumps(label_map, indent=4)}",
        "",
    ]

    with open(PYTHON_DATA_PATH, "w") as f:
        f.write("\n".join(lines))
    typer.echo(f"Generated {PYTHON_DATA_PATH}")


def generate_typescript_interfaces(data: dict[str, Any]):
    lines = [
        "/**",
        " * Fraud Taxonomy Types",
        " *",
        " * Re-exported from @i4g/sdk (canonical source).",
        " * The SDK Zod schemas are the single source of truth; these re-exports",
        " * are provided for convenience so that consumers can import from either",
        " * @i4g/sdk or @i4g/types.",
        " */",
        'export type {',
        '  TaxonomyItem,',
        '  TaxonomyAxis,',
        '  TaxonomyResponse as TaxonomyDefinitions,',
        '} from "@i4g/sdk";',
        "",
    ]

    # Ensure directory exists
    TS_ENUMS_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(TS_ENUMS_PATH, "w") as f:
        f.write("\n".join(lines))
    typer.echo(f"Generated {TS_ENUMS_PATH}")


def generate_markdown_docs(data: dict[str, Any]):
    lines = [
        "# Fraud Taxonomy Reference",
        "",
        f'**Version:** {data["version"]}',
        "",
        "This document is auto-generated from the taxonomy definitions.",
        "",
    ]

    def add_section(title: str, items: list[dict[str, str]]):
        lines.append(f"## {title}")
        lines.append("")
        lines.append("| Code | Label | Description |")
        lines.append("|---|---|---|")
        for item in items:
            lines.append(f'| `{item["code"]}` | {item["label"]} | {item["description"]} |')
        lines.append("")

    add_section("Scam Intent", data["intents"])
    add_section("Delivery Channel", data["channels"])
    add_section("Social Engineering Techniques", data["techniques"])
    add_section("Requested Actions", data["actions"])
    add_section("Claimed Personas", data["personas"])

    # Ensure directory exists
    DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(DOCS_PATH, "w") as f:
        f.write("\n".join(lines))
    typer.echo(f"Generated {DOCS_PATH}")


import subprocess


@taxonomy_app.command("refresh")
def refresh_taxonomy():
    """
    Regenerate static data.py, TypeScript interfaces (types), and Markdown docs from definitions.yaml.
    """
    try:
        data = load_definitions()
        # generate_python_enums(data) # backend models usually need this, but we are moving to dynamic.
        # Keeping generate_python_enums for now as models.py depends on it, but updating docstring to reflect primary artifacts.
        generate_python_enums(data)
        generate_taxonomy_data(data)
        generate_typescript_interfaces(data)
        generate_markdown_docs(data)

        # Attempt to format the generated TypeScript file
        ui_dir = WORKSPACE_ROOT / "ui"
        if ui_dir.exists():
            try:
                subprocess.run(
                    ["pnpm", "prettier", "--write", str(TS_ENUMS_PATH)],
                    cwd=ui_dir,
                    check=False,  # Don't fail if pnpm/prettier is missing
                    capture_output=True,
                )
                typer.echo("Formatted TypeScript enums.")
            except Exception:
                typer.echo("Skipped formatting TypeScript enums (pnpm/prettier not found or failed).")

        typer.echo("Taxonomy refresh complete.")
    except Exception as e:
        typer.echo(f"Error refreshing taxonomy: {e}", err=True)
        raise typer.Exit(code=1)
