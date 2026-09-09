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

# Sections and keys from https://learn.chatgpt.com/docs/build-skills. Values inside
# `dependencies.tools` are a list of tool entries and are not checked here.
OPENAI_METADATA_KEYS = {
    "interface": {
        "display_name",
        "short_description",
        "icon_small",
        "icon_large",
        "brand_color",
        "default_prompt",
    },
    "policy": {"allow_implicit_invocation"},
    "dependencies": {"tools"},
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

    # Optional per-host metadata: agents/openai.yaml in the agent-skills spec.
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
            unknown = sorted(set(value) - allowed)
            if unknown:
                errors.append(f"ERROR {metadata_path.relative_to(ROOT)}: unknown `{section}` keys {unknown}")
        unknown_sections = sorted(set(metadata) - set(OPENAI_METADATA_KEYS))
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
