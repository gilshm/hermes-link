import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_link.org import AgentConfig
from hermes_link.status import inspect_agent, yes_no


class StatusTests(unittest.TestCase):
    def test_inspect_agent_reports_local_install_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            hermes_home = Path(tmpdir)
            (hermes_home / "profiles" / "agent_a" / "skills" / "agent-comms").mkdir(parents=True)
            (hermes_home / "profiles" / "agent_a" / "skills" / "agent-comms" / "SKILL.md").write_text("", encoding="utf-8")
            (hermes_home / "profiles" / "agent_a" / "plugins" / "hermes-link").mkdir(parents=True)
            (hermes_home / "profiles" / "agent_a" / "plugins" / "hermes-link" / "plugin.yaml").write_text("", encoding="utf-8")
            agent = AgentConfig("agent_a", "agent_a", "Coordinator")

            with (
                mock.patch("shutil.which", return_value="/bin/agent_a"),
                mock.patch(
                    "subprocess.run",
                    return_value=subprocess.CompletedProcess(
                        ["agent_a"], 0, stdout="enabled user 0.1.0 hermes-link\n", stderr=""
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


if __name__ == "__main__":
    unittest.main()
