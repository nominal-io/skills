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
