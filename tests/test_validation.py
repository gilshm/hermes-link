import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_link.validation import validate_org


class ValidationTests(unittest.TestCase):
    def test_validate_org_accepts_valid_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            org = _write_repo(root, expertise="Coordinator")

            with mock.patch("hermes_link.validation.shutil.which", return_value="/bin/hl_ceo"):
                errors = validate_org(org, repo_root=root)

        self.assertEqual(errors, [])

    def test_validate_org_reports_missing_expertise_and_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            org = _write_repo(root, expertise="")

            with mock.patch("hermes_link.validation.shutil.which", return_value=None):
                errors = validate_org(org, repo_root=root)

        self.assertIn("agent hl_ceo is missing expertise", errors)
        self.assertIn("agent hl_ceo command not found: hl_ceo", errors)

    def test_validate_org_rejects_old_routing_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            org = _write_repo(root, expertise="Coordinator")
            org.write_text(
                org.read_text(encoding="utf-8")
                + "\n".join(
                    [
                        "\nrouting:",
                        "  default: deny",
                        "  allow:",
                        "    hl_ceo:",
                        "      - '*'",
                    ]
                ),
                encoding="utf-8",
            )

            errors = validate_org(org, repo_root=root)

        self.assertIn("routing must be flat or strict_hierarchical", errors)


def _write_repo(root: Path, *, expertise: str) -> Path:
    skill = root / "skills" / "agent-comms" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("skill", encoding="utf-8")
    plugin = root / ".hermes" / "plugins" / "hermes-link" / "plugin.yaml"
    plugin.parent.mkdir(parents=True)
    plugin.write_text("name: hermes-link", encoding="utf-8")
    org = root / "config" / "org.yaml"
    org.parent.mkdir()
    org.write_text(
        "\n".join(
            [
                "agents:",
                "  hl_ceo:",
                "    command: hl_ceo",
                f'    expertise: "{expertise}"',
                "skill: skills/agent-comms/SKILL.md",
            ]
        ),
        encoding="utf-8",
    )
    return org


if __name__ == "__main__":
    unittest.main()
