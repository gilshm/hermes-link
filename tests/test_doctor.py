import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_link.doctor import run_doctor
from hermes_link.hermes_runner import RoutedSend
from hermes_link.message import Message


class DoctorTests(unittest.TestCase):
    def test_run_doctor_reports_static_install_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            hermes_home = root / "hermes"
            org = _write_repo(root)
            (hermes_home / "profiles" / "hl_ceo" / "skills" / "agent-comms").mkdir(parents=True)
            (hermes_home / "profiles" / "hl_ceo" / "skills" / "agent-comms" / "SKILL.md").write_text(
                "skill",
                encoding="utf-8",
            )
            (hermes_home / "profiles" / "hl_ceo" / "plugins" / "hermes-link").mkdir(parents=True)
            (hermes_home / "profiles" / "hl_ceo" / "plugins" / "hermes-link" / "plugin.yaml").write_text(
                "name: hermes-link",
                encoding="utf-8",
            )

            with (
                mock.patch("hermes_link.validation.shutil.which", return_value="/bin/hl_ceo"),
                mock.patch("hermes_link.status.shutil.which", return_value="/bin/hl_ceo"),
                mock.patch("hermes_link.status._plugin_enabled", return_value=True),
            ):
                checks = run_doctor(org_path=org, repo_root=root, hermes_home=hermes_home)

        self.assertTrue(all(check.ok for check in checks))
        self.assertEqual([check.name for check in checks], ["org config", "state dir", "agent hl_ceo"])

    def test_run_doctor_reports_static_route_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            hermes_home = root / "hermes"
            org = _write_strict_repo(root)

            with (
                mock.patch("hermes_link.validation.shutil.which", return_value="/bin/hermes"),
                mock.patch("hermes_link.status.shutil.which", return_value="/bin/hermes"),
                mock.patch("hermes_link.status._plugin_enabled", return_value=True),
            ):
                checks = run_doctor(
                    org_path=org,
                    repo_root=root,
                    hermes_home=hermes_home,
                    route_matrix=True,
                    route_from="hl_advisor",
                )

        route_checks = [check for check in checks if check.name.startswith("route ")]
        self.assertEqual(
            [(check.name, check.ok, check.detail) for check in route_checks],
            [
                ("route hl_advisor -> hl_backend_engineer", True, "blocked by policy"),
                ("route hl_advisor -> hl_ceo", True, "allowed"),
            ],
        )

    def test_run_doctor_live_route_matrix_compares_real_behavior_to_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            hermes_home = root / "hermes"
            org = _write_strict_repo(root)

            def fake_request_send(sender: str, prompt: str) -> RoutedSend:
                recipient = prompt.rsplit("\nSEND ", 1)[1].split(":", 1)[0]
                if sender == "hl_advisor" and recipient == "hl_backend_engineer":
                    raise RuntimeError(
                        "Hermes Link routing policy blocked this message: hl_advisor may not send to hl_backend_engineer."
                    )
                return RoutedSend(Message(sender, recipient, "ok"), mock.Mock())

            with (
                mock.patch("hermes_link.validation.shutil.which", return_value="/bin/hermes"),
                mock.patch("hermes_link.status.shutil.which", return_value="/bin/hermes"),
                mock.patch("hermes_link.status._plugin_enabled", return_value=True),
                mock.patch("hermes_link.doctor.HermesRunner") as runner,
            ):
                runner.return_value.request_send.side_effect = fake_request_send
                checks = run_doctor(
                    org_path=org,
                    repo_root=root,
                    hermes_home=hermes_home,
                    live_route_matrix=True,
                    route_from="hl_advisor",
                )

        live_checks = [check for check in checks if check.name.startswith("live route ")]
        self.assertEqual(
            [(check.name, check.ok, check.detail) for check in live_checks],
            [
                ("live route hl_advisor -> hl_backend_engineer", True, "blocked by policy"),
                ("live route hl_advisor -> hl_ceo", True, "allowed: hl_advisor -> hl_ceo"),
            ],
        )


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
                "  hl_ceo:",
                "    command: hl_ceo",
                "    expertise: Coordinator",
                "skill: skills/agent-comms/SKILL.md",
            ]
        ),
        encoding="utf-8",
    )
    return org


def _write_strict_repo(root: Path) -> Path:
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
                "    expertise: CEO",
                "  hl_advisor:",
                "    command: hl_advisor",
                "    expertise: Advisor",
                "    manager: hl_ceo",
                "  hl_backend_engineer:",
                "    command: hl_backend_engineer",
                "    expertise: Backend",
                "routing: strict_hierarchical",
                "skill: skills/agent-comms/SKILL.md",
            ]
        ),
        encoding="utf-8",
    )
    return org


if __name__ == "__main__":
    unittest.main()
