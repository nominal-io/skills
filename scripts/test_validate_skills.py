#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.2"]
# ///
"""Exercise the validator CLI against isolated skill packages."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class MetadataValidationTest(unittest.TestCase):
    def validate(self, metadata: str | None) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            validator = scripts / "validate_skills.py"
            shutil.copyfile(Path(__file__).with_name("validate_skills.py"), validator)
            skill = root / "skills" / "example"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text(
                "---\nname: example\ndescription: Example workflow\n---\n", encoding="utf-8"
            )
            for name in (
                ".claude-plugin/plugin.json", ".claude-plugin/marketplace.json",
                ".codex-plugin/plugin.json", ".agents/plugins/marketplace.json",
            ):
                manifest = root / name
                manifest.parent.mkdir(parents=True, exist_ok=True)
                manifest.write_text("{}", encoding="utf-8")
            if metadata is not None:
                (skill / "agents").mkdir()
                (skill / "agents/openai.yaml").write_text(metadata, encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(validator)], capture_output=True, text=True, check=False
            )

    def test_optional_and_valid_metadata(self) -> None:
        for metadata in (None, "{}", 'interface:\n  display_name: "Example"\n'
                         'policy:\n  allow_implicit_invocation: false\n'
                         'dependencies:\n  tools: []\n'):
            with self.subTest(metadata=metadata):
                result = self.validate(metadata)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_invalid_metadata_has_actionable_error(self) -> None:
        cases = (
            ("interface: [", "invalid YAML"),
            ("[]", "mapping"),
            ("interface: []", "mapping"),
            ("interface:\n  typo: x", "unknown"),
            ("typo: {}", "unknown"),
            ("interface:\n  display_name: [x]", "string"),
            ("interface:\n  default_prompt: 12", "string"),
            ('policy:\n  allow_implicit_invocation: "false"', "bool"),
            ("policy:\n  allow_implicit_invocation: 0", "bool"),
            ("dependencies:\n  tools: not-a-list", "list"),
            ("interface:\n  display_name: null", "string"),
            ("interface:\n  1: x\n  typo: x", "unknown"),
        )
        for metadata, expected in cases:
            with self.subTest(metadata=metadata):
                result = self.validate(metadata)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assertIn("skills/example/agents/openai.yaml", result.stdout)
                self.assertIn(expected, result.stdout)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
