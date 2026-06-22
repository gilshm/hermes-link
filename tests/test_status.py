import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_link.org import AgentConfig
from hermes_link.status import check_agent_health, inspect_agent, yes_no


class StatusTests(unittest.TestCase):
    def test_inspect_agent_reports_local_install_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hermes_home = Path(tmpdir)
            (hermes_home / "profiles" / "hl_ceo" / "skills" / "agent-comms").mkdir(parents=True)
            (hermes_home / "profiles" / "hl_ceo" / "skills" / "agent-comms" / "SKILL.md").write_text("", encoding="utf-8")
            (hermes_home / "profiles" / "hl_ceo" / "plugins" / "hermes-link").mkdir(parents=True)
            (hermes_home / "profiles" / "hl_ceo" / "plugins" / "hermes-link" / "plugin.yaml").write_text("", encoding="utf-8")
            agent = AgentConfig("hl_ceo", "hl_ceo", "Coordinator")

            with (
                mock.patch("shutil.which", return_value="/bin/hl_ceo"),
                mock.patch(
                    "subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        ["hl_ceo"], 0, stdout="enabled user 0.1.0 hermes-link\n", stderr=""
                    ),
                ),
            ):
                status = inspect_agent(agent, hermes_home=hermes_home)

        self.assertTrue(status.command_available)
        self.assertTrue(status.skill_installed)
        self.assertTrue(status.plugin_installed)
        self.assertTrue(status.plugin_enabled)

    def test_yes_no(self) -> None:
        self.assertEqual(yes_no(True), "yes")
        self.assertEqual(yes_no(False), "no")
        self.assertEqual(yes_no(None), "unknown")

    def test_check_agent_health_runs_smoke_prompt(self) -> None:
        agent = AgentConfig("hl_ceo", "hl_ceo", "Coordinator")

        with (
            mock.patch("hermes_link.status.shutil.which", return_value="/bin/hl_ceo"),
            mock.patch(
                "hermes_link.status.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    ["hl_ceo"], 0, stdout="session_id: s1\nHERMES_LINK_HEALTH_OK\n", stderr=""
                ),
            ) as run,
        ):
            health = check_agent_health(agent, timeout=3)

        self.assertTrue(health.ok)
        self.assertEqual(health.response, "HERMES_LINK_HEALTH_OK")
        self.assertIn("-q", run.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
