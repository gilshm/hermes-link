import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_link.doctor import run_doctor


class DoctorTests(unittest.TestCase):
    def test_run_doctor_reports_static_install_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            hermes_home = root / "hermes"
            org = _write_repo(root)
            (hermes_home / "profiles" / "agent_a" / "skills" / "agent-comms").mkdir(parents=True)
            (hermes_home / "profiles" / "agent_a" / "skills" / "agent-comms" / "SKILL.md").write_text(
                "skill",
                encoding="utf-8",
            )
            (hermes_home / "profiles" / "agent_a" / "plugins" / "hermes-link").mkdir(parents=True)
            (hermes_home / "profiles" / "agent_a" / "plugins" / "hermes-link" / "plugin.yaml").write_text(
                "name: hermes-link",
                encoding="utf-8",
            )

            with (
                mock.patch("hermes_link.validation.shutil.which", return_value="/bin/agent_a"),
                mock.patch("hermes_link.status.shutil.which", return_value="/bin/agent_a"),
                mock.patch("hermes_link.status._plugin_enabled", return_value=True),
            ):
                checks = run_doctor(org_path=org, repo_root=root, hermes_home=hermes_home)

        self.assertTrue(all(check.ok for check in checks))
        self.assertEqual([check.name for check in checks], ["org config", "state dir", "agent agent_a"])


def _write_repo(root: Path) -> Path:
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
                "  agent_a:",
                "    command: agent_a",
                "    expertise: Coordinator",
                "skill: skills/agent-comms/SKILL.md",
            ]
        ),
        encoding="utf-8",
    )
    return org


if __name__ == "__main__":
    unittest.main()
