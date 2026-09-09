#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.2"]
# ///
"""Check skill frontmatter and plugin manifests."""

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
errors: list[str] = []

# Supported metadata fields from https://learn.chatgpt.com/docs/build-skills.
# Validate field types; individual dependency tool entries are not checked here.
OPENAI_METADATA_KEYS = {
    "interface": {
        "display_name": str,
        "short_description": str,
        "icon_small": str,
        "icon_large": str,
        "brand_color": str,
        "default_prompt": str,
    },
    "policy": {"allow_implicit_invocation": bool},
    "dependencies": {"tools": list},
}

for directory in sorted((ROOT / "skills").iterdir()):
    if not directory.is_dir():
        continue
    path = directory / "SKILL.md"
    if not path.is_file():
        errors.append(f"ERROR {path.relative_to(ROOT)}: missing SKILL.md")
        continue
    parts = path.read_text(encoding="utf-8").split("---", 2)
    if len(parts) != 3:
        errors.append(f"ERROR {path.relative_to(ROOT)}: missing YAML frontmatter")
        continue
    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        errors.append(f"ERROR {path.relative_to(ROOT)}: invalid YAML frontmatter: {exc}")
        continue
    if not isinstance(frontmatter, dict):
        errors.append(f"ERROR {path.relative_to(ROOT)}: frontmatter must be a YAML mapping")
        continue
    if frontmatter.get("name") != directory.name:
        errors.append(f"ERROR {path.relative_to(ROOT)}: frontmatter name must match directory {directory.name!r}")
    if not isinstance(frontmatter.get("description"), str) or not frontmatter["description"].strip():
        errors.append(f"ERROR {path.relative_to(ROOT)}: frontmatter description must be a non-empty string")

    # Optional OpenAI-specific metadata; other hosts can omit it.
    metadata_path = directory / "agents" / "openai.yaml"
    if metadata_path.is_file():
        try:
            metadata = yaml.safe_load(metadata_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            errors.append(f"ERROR {metadata_path.relative_to(ROOT)}: invalid YAML: {exc}")
            continue
        if not isinstance(metadata, dict):
            errors.append(f"ERROR {metadata_path.relative_to(ROOT)}: must be a YAML mapping")
            continue
        for section, allowed in OPENAI_METADATA_KEYS.items():
            value = metadata.get(section)
            if value is None:
                continue
            if not isinstance(value, dict):
                errors.append(f"ERROR {metadata_path.relative_to(ROOT)}: `{section}` must be a mapping")
                continue
            unknown = sorted(set(value) - set(allowed), key=str)
            if unknown:
                errors.append(f"ERROR {metadata_path.relative_to(ROOT)}: unknown `{section}` keys {unknown}")
            for key, expected_type in allowed.items():
                if key in value and not isinstance(value[key], expected_type):
                    type_name = "string" if expected_type is str else expected_type.__name__
                    errors.append(
                        f"ERROR {metadata_path.relative_to(ROOT)}: `{section}.{key}` must be a {type_name}"
                    )
        unknown_sections = sorted(set(metadata) - set(OPENAI_METADATA_KEYS), key=str)
        if unknown_sections:
            errors.append(f"ERROR {metadata_path.relative_to(ROOT)}: unknown top-level keys {unknown_sections}")
for path in (
    ROOT / ".claude-plugin/plugin.json",
    ROOT / ".claude-plugin/marketplace.json",
    ROOT / ".codex-plugin/plugin.json",
    ROOT / ".agents/plugins/marketplace.json",
):
    try:
        with path.open(encoding="utf-8") as handle:
            json.load(handle)
    except FileNotFoundError:
        errors.append(f"ERROR {path.relative_to(ROOT)}: manifest does not exist")
    except json.JSONDecodeError as exc:
        errors.append(f"ERROR {path.relative_to(ROOT)}: invalid JSON on line {exc.lineno}: {exc.msg}")
if errors:
    print("\n".join(errors))
    sys.exit(1)

print("Validation passed.")
