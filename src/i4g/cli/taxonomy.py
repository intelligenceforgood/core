import typer
import yaml
import json
from pathlib import Path
from typing import Dict, List, Any

taxonomy_app = typer.Typer(help="Manage fraud taxonomy definitions and code generation.")

# Paths
# core/src/i4g/cli/taxonomy.py -> core/src/i4g/cli -> core/src/i4g -> core/src -> core
CORE_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = CORE_ROOT.parent
DEFINITIONS_PATH = CORE_ROOT / "src/i4g/taxonomy/definitions.yaml"
PYTHON_ENUMS_PATH = CORE_ROOT / "src/i4g/taxonomy/enums.py"
TS_ENUMS_PATH = WORKSPACE_ROOT / "ui/packages/types/src/taxonomy.ts"
DOCS_PATH = WORKSPACE_ROOT / "docs/book/api/taxonomy_reference.md"


def load_definitions() -> Dict[str, Any]:
    with open(DEFINITIONS_PATH, "r") as f:
        return yaml.safe_load(f)


def generate_python_enums(data: Dict[str, Any]):
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
    def add_enum(class_name: str, items: List[Dict[str, str]]):
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


def generate_typescript_enums(data: Dict[str, Any]):
    lines = [
        "/**",
        " * Fraud Taxonomy Enums",
        f' * Version: fraud-taxonomy.v{data["version"]}',
        " *",
        " * Auto-generated from definitions.yaml. DO NOT EDIT.",
        " */",
        "",
    ]

    def add_enum(enum_name: str, items: List[Dict[str, Any]]):
        lines.append(f"export enum {enum_name} {{")
        for item in items:
            key = item["code"].split(".")[-1]
            lines.append(f'  /** {item["description"]} */')
            lines.append(f'  {key} = "{item["code"]}",')
        lines.append("}")
        lines.append("")

        # Generate description map
        lines.append(f"export const {enum_name}Descriptions: Record<{enum_name}, string> = {{")
        for item in items:
            key = item["code"].split(".")[-1]
            # Escape quotes in description just in case
            desc = item["description"].replace('"', '\\"')
            lines.append(f'  [{enum_name}.{key}]: "{desc}",')
        lines.append("};")
        lines.append("")

        # Generate Label map
        lines.append(f"export const {enum_name}Labels: Record<{enum_name}, string> = {{")
        for item in items:
            key = item["code"].split(".")[-1]
            label = item.get("label", key).replace('"', '\\"')
            lines.append(f'  [{enum_name}.{key}]: "{label}",')
        lines.append("};")
        lines.append("")

        # Generate Examples map
        lines.append(f"export const {enum_name}Examples: Record<{enum_name}, string[]> = {{")
        for item in items:
            key = item["code"].split(".")[-1]
            examples = item.get("examples", [])
            ex_str = json.dumps(examples)
            lines.append(f"  [{enum_name}.{key}]: {ex_str},")
        lines.append("};")
        lines.append("")

    add_enum("ScamIntent", data["intents"])
    add_enum("DeliveryChannel", data["channels"])
    add_enum("SocialEngineeringTechnique", data["techniques"])
    add_enum("RequestedAction", data["actions"])
    add_enum("ClaimedPersona", data["personas"])

    # Ensure directory exists
    TS_ENUMS_PATH.parent.mkdir(parents=True, exist_ok=True)

    with open(TS_ENUMS_PATH, "w") as f:
        f.write("\n".join(lines))
    typer.echo(f"Generated {TS_ENUMS_PATH}")


def generate_markdown_docs(data: Dict[str, Any]):
    lines = [
        "# Fraud Taxonomy Reference",
        "",
        f'**Version:** {data["version"]}',
        "",
        "This document is auto-generated from the taxonomy definitions.",
        "",
    ]

    def add_section(title: str, items: List[Dict[str, str]]):
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
    Regenerate Python enums, TypeScript enums, and Markdown docs from definitions.yaml.
    """
    try:
        data = load_definitions()
        generate_python_enums(data)
        generate_typescript_enums(data)
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
