#!/usr/bin/env python3
"""Validate skills, plugin manifests, and the README skill catalog."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent.parent
MAX_DESCRIPTION_LENGTH = 1024
MANIFESTS = (
    ROOT / ".claude-plugin/plugin.json",
    ROOT / ".claude-plugin/marketplace.json",
    ROOT / ".codex-plugin/plugin.json",
    ROOT / ".agents/plugins/marketplace.json",
)


class Validator:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.passed: list[str] = []

    def error(self, path: Path, message: str, line: int | None = None) -> None:
        relative = path.relative_to(ROOT)
        location = f"{relative}:{line}" if line is not None else str(relative)
        self.errors.append(f"ERROR {location}: {message}")

    def check(self, description: str, starting_errors: int) -> None:
        if len(self.errors) == starting_errors:
            self.passed.append(description)


def parse_frontmatter(path: Path, validator: Validator) -> dict[str, str | list[str]] | None:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        validator.error(path, "missing YAML frontmatter opening delimiter", 1)
        return None

    end = next((index for index, line in enumerate(lines[1:], 1) if line == "---"), None)
    if end is None:
        validator.error(path, "missing YAML frontmatter closing delimiter")
        return None

    values: dict[str, str | list[str]] = {}
    valid = True
    line_index = 1
    while line_index < end:
        line_number = line_index + 1
        line = lines[line_index]
        if not line.strip():
            line_index += 1
            continue
        match = re.fullmatch(r"([A-Za-z0-9_-]+):[ \t]*(.*)", line)
        if not match:
            validator.error(
                path,
                "frontmatter must contain simple `key: value` lines or indented `- item` lists",
                line_number,
            )
            valid = False
            line_index += 1
            continue
        key, value = match.groups()
        if key in values:
            validator.error(path, f"duplicate frontmatter key {key!r}", line_number)
            valid = False
        value = value.strip()
        if value in {"|", ">", "|-", "|+", ">-", ">+"}:
            validator.error(path, "multi-line scalar frontmatter values are not supported", line_number)
            valid = False
            line_index += 1
            continue
        if not value:
            items: list[str] = []
            next_index = line_index + 1
            while next_index < end:
                item_match = re.fullmatch(r"[ \t]+-[ \t]*(.+)", lines[next_index])
                if not item_match:
                    break
                items.append(item_match.group(1).strip())
                next_index += 1
            values[key] = items if items else value
            line_index = next_index
            continue
        values[key] = value
        line_index += 1
    return values if valid else None


def validate_skill_files(validator: Validator) -> list[str]:
    frontmatter_start = len(validator.errors)
    skills_root = ROOT / "skills"
    skill_names: list[str] = []
    if not skills_root.is_dir():
        validator.error(skills_root, "skills directory does not exist")
        return skill_names

    markdown_files: list[Path] = []
    for skill_dir in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_names.append(skill_dir.name)
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            validator.error(skill_file, "every skill directory must contain SKILL.md")
            continue

        frontmatter = parse_frontmatter(skill_file, validator)
        if frontmatter is None:
            continue
        name = frontmatter.get("name")
        description = frontmatter.get("description")
        if not isinstance(name, str) or not name.strip():
            validator.error(skill_file, "frontmatter name must be a non-empty scalar string")
        elif name != skill_dir.name:
            validator.error(
                skill_file,
                f"frontmatter name {name!r} must match directory {skill_dir.name!r}",
            )
        if not isinstance(description, str) or not description.strip():
            validator.error(skill_file, "frontmatter description must be a non-empty scalar string")
        elif len(description) > MAX_DESCRIPTION_LENGTH:
            validator.error(
                skill_file,
                f"description is {len(description)} characters; the Agent Skills convention "
                f"limits descriptions to {MAX_DESCRIPTION_LENGTH} characters",
            )

        markdown_files.extend([skill_file, *sorted((skill_dir / "references").glob("*.md"))])

    validator.check(f"{len(skill_names)} skill directories and their frontmatter", frontmatter_start)
    links_start = len(validator.errors)
    validate_markdown_links(markdown_files, validator)
    validator.check("relative markdown links in skills and references", links_start)
    return skill_names


def validate_markdown_links(paths: list[Path], validator: Validator) -> None:
    link_pattern = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for raw_target in link_pattern.findall(line):
                target = raw_target.strip()
                if target.startswith("<") and ">" in target:
                    target = target[1 : target.index(">")]
                else:
                    target = target.split()[0]
                parsed = urlsplit(target)
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                destination = (path.parent / parsed.path).resolve()
                if not destination.is_file():
                    validator.error(
                        path,
                        f"relative markdown link does not resolve: {target}",
                        line_number,
                    )


def load_json(path: Path, validator: Validator) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        validator.error(path, "required manifest does not exist")
        return None
    except json.JSONDecodeError as error:
        validator.error(path, f"invalid JSON: {error.msg}", error.lineno)
        return None
    if not isinstance(value, dict):
        validator.error(path, "top-level JSON value must be an object")
        return None
    return value


def require_string(data: dict[str, Any], key: str, path: Path, validator: Validator) -> str | None:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        validator.error(path, f"required non-empty string field {key!r} is missing")
        return None
    return value


def validate_manifests(validator: Validator) -> None:
    manifests_start = len(validator.errors)
    claude_plugin_path, claude_marketplace_path, codex_plugin_path, codex_marketplace_path = MANIFESTS
    claude_plugin = load_json(claude_plugin_path, validator)
    claude_marketplace = load_json(claude_marketplace_path, validator)
    codex_plugin = load_json(codex_plugin_path, validator)
    codex_marketplace = load_json(codex_marketplace_path, validator)
    if not all((claude_plugin, claude_marketplace, codex_plugin, codex_marketplace)):
        validator.check("Claude Code and Codex plugin manifests and marketplaces", manifests_start)
        return

    claude_name = require_string(claude_plugin, "name", claude_plugin_path, validator)
    codex_name = require_string(codex_plugin, "name", codex_plugin_path, validator)
    require_string(claude_plugin, "description", claude_plugin_path, validator)
    require_string(claude_plugin, "version", claude_plugin_path, validator)
    require_string(codex_plugin, "description", codex_plugin_path, validator)
    require_string(codex_plugin, "version", codex_plugin_path, validator)
    if claude_name and codex_name and claude_name != codex_name:
        validator.error(
            codex_plugin_path,
            f"plugin name {codex_name!r} does not match Claude plugin name {claude_name!r}",
        )

    claude_author = claude_plugin.get("author")
    codex_author = codex_plugin.get("author")
    for author, path in ((claude_author, claude_plugin_path), (codex_author, codex_plugin_path)):
        if not isinstance(author, dict) or not isinstance(author.get("name"), str) or not author["name"].strip():
            validator.error(path, "author.name must be a non-empty string")

    skills_value = codex_plugin.get("skills")
    if not isinstance(skills_value, str) or not skills_value.strip():
        validator.error(codex_plugin_path, "required non-empty string field 'skills' is missing")
    else:
        skills_path = (ROOT / skills_value).resolve()
        if not skills_path.is_dir():
            validator.error(codex_plugin_path, f"skills path does not resolve to a directory: {skills_value}")

    validate_marketplace(claude_marketplace, claude_marketplace_path, claude_name, validator, "Claude")
    validate_marketplace(codex_marketplace, codex_marketplace_path, codex_name, validator, "Codex")
    validator.check("Claude Code and Codex plugin manifests and marketplaces", manifests_start)


def validate_marketplace(
    marketplace: dict[str, Any],
    path: Path,
    plugin_name: str | None,
    validator: Validator,
    platform: str,
) -> None:
    require_string(marketplace, "name", path, validator)
    plugins = marketplace.get("plugins")
    if not isinstance(plugins, list) or not plugins:
        validator.error(path, "required non-empty array field 'plugins' is missing")
        return

    matching_entry = False
    for index, entry in enumerate(plugins):
        entry_path = path
        if not isinstance(entry, dict):
            validator.error(entry_path, f"{platform} marketplace plugin entry {index} must be an object")
            continue
        entry_name = require_string(entry, "name", entry_path, validator)
        if entry_name == plugin_name:
            matching_entry = True

        source = entry.get("source")
        if platform == "Claude":
            if not isinstance(source, str) or not source.startswith("./"):
                validator.error(entry_path, f"Claude marketplace entry {index} source must be a `./` path")
                continue
            source_path = (ROOT / source).resolve()
        else:
            if not isinstance(source, dict) or source.get("source") != "local":
                validator.error(entry_path, f"Codex marketplace entry {index} source must be local")
                continue
            source_path_value = source.get("path")
            if not isinstance(source_path_value, str) or not source_path_value.startswith("./"):
                validator.error(entry_path, f"Codex marketplace entry {index} source.path must be a `./` path")
                continue
            source_path = (ROOT / source_path_value).resolve()

        if not source_path.is_dir():
            validator.error(entry_path, f"marketplace entry {index} source path does not resolve: {source_path}")

    if plugin_name and not matching_entry:
        validator.error(path, f"marketplace has no plugin entry named {plugin_name!r}")


def validate_readme_catalog(skill_names: list[str], validator: Validator) -> None:
    catalog_start = len(validator.errors)
    path = ROOT / "README.md"
    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index("## Skills") + 1
    except ValueError:
        validator.error(path, "missing `## Skills` section")
        validator.check("README skill catalog (0 skills)", catalog_start)
        return
    end = next((index for index in range(start, len(lines)) if lines[index].startswith("## ")), len(lines))

    rows: list[tuple[str, int, str]] = []
    row_pattern = re.compile(r"^\|\s*`([^`]+)`\s*\|.*\|([^|]+)\|\s*$")
    for index in range(start, end):
        match = row_pattern.match(lines[index])
        if match:
            rows.append((match.group(1), index + 1, match.group(2).strip()))

    catalog_names = [name for name, _, _ in rows]
    for name, line, link_cell in rows:
        expected_link = f"[`SKILL.md`](skills/{name}/SKILL.md)"
        if expected_link not in link_cell:
            validator.error(path, f"catalog row for {name!r} must link to {expected_link}", line)
    if len(catalog_names) != len(set(catalog_names)):
        validator.error(path, "skill catalog contains duplicate skill rows")
    if set(catalog_names) != set(skill_names):
        missing = sorted(set(skill_names) - set(catalog_names))
        stale = sorted(set(catalog_names) - set(skill_names))
        details = []
        if missing:
            details.append(f"missing {missing}")
        if stale:
            details.append(f"stale {stale}")
        validator.error(path, "skill catalog does not match skills/: " + ", ".join(details))
    validator.check(f"README skill catalog ({len(catalog_names)} skills)", catalog_start)


def main() -> int:
    validator = Validator()
    skill_names = validate_skill_files(validator)
    validate_manifests(validator)
    validate_readme_catalog(skill_names, validator)

    for error in validator.errors:
        print(error)
    print(f"Validation summary: {len(validator.passed)} checks passed, {len(validator.errors)} failure(s).")
    if not validator.errors:
        print("All skills, manifests, links, and README catalog entries are valid.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
