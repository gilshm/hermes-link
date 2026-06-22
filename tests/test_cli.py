import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from hermes_link.cli import main
from hermes_link.hermes_runner import AgentTurn, ChatResult
from hermes_link.log import EventLog
from hermes_link.message import Message


class CliTests(unittest.TestCase):
    def test_log_command_prints_formatted_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            EventLog(path).write("message", thread_id="thread-1", from_agent="hl_ceo", to_agent="hl_advisor", body="hello")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["log", "--path", str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("[thread-1] ├─ hl_ceo -> hl_advisor: hello", output.getvalue())

    def test_log_command_can_force_color(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            EventLog(path).write("message", thread_id="thread-1", from_agent="hl_ceo", to_agent="hl_advisor", body="hello")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["log", "--path", str(path), "--color", "always"])

        self.assertEqual(exit_code, 0)
        self.assertIn("\033[", output.getvalue())

    def test_trace_command_prints_matching_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            EventLog(path).write("message", thread_id="thread-1", from_agent="hl_ceo", to_agent="hl_advisor", body="hello")
            EventLog(path).write("message", thread_id="thread-2", from_agent="hl_ceo", to_agent="hl_advisor", body="ignore")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["trace", "thread-1", "--path", str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("Trace thread-1", output.getvalue())
        self.assertIn("hello", output.getvalue())
        self.assertNotIn("ignore", output.getvalue())

    def test_sessions_command_prints_session_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session-map.json"
            path.write_text('{"source-a:hl_advisor": "session-b"}', encoding="utf-8")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["sessions", "--path", str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("source-a -> hl_advisor: session-b", output.getvalue())

    def test_chat_command_labels_final_routed_reply(self) -> None:
        output = io.StringIO()
        result = ChatResult(
            transcript=[
                Message("user", "hl_ceo", "start"),
                Message("hl_ceo", "hl_advisor", "ping"),
            ],
            turns=[
                AgentTurn("hl_ceo", "session-a", "SEND hl_advisor: ping"),
                AgentTurn("hl_advisor", "session-b", "pong"),
            ],
            final_response="pong",
        )

        with (
            mock.patch("sys.stdout", output),
            mock.patch("hermes_link.cli.load_org"),
            mock.patch("hermes_link.cli.EventLog"),
            mock.patch("hermes_link.cli.HermesRunner") as runner,
        ):
            runner.return_value.chat.return_value = result
            exit_code = main(["chat", "hl_ceo", "start"])

        self.assertEqual(exit_code, 0)
        self.assertIn("hl_ceo -> hl_advisor: ping", output.getvalue())
        self.assertIn("hl_advisor -> hl_ceo: pong", output.getvalue())

    def test_org_validate_command_reports_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
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
            skill = root / "skills" / "agent-comms" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("skill", encoding="utf-8")
            plugin = root / ".hermes" / "plugins" / "hermes-link" / "plugin.yaml"
            plugin.parent.mkdir(parents=True)
            plugin.write_text("name: hermes-link", encoding="utf-8")
            output = io.StringIO()

            with (
                mock.patch("sys.stdout", output),
                mock.patch("hermes_link.validation.shutil.which", return_value="/bin/hl_ceo"),
                mock.patch("hermes_link.cli.REPO_ROOT", root),
            ):
                exit_code = main(["org", "validate", "--org", str(org)])

        self.assertEqual(exit_code, 0)
        self.assertIn("org config ok", output.getvalue())

    def test_org_graph_command_prints_hierarchy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            org = root / "config" / "org.yaml"
            org.parent.mkdir()
            org.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "    title: CEO",
                        "    expertise: Coordinator",
                        "  hl_cto:",
                        "    command: hl_cto",
                        "    title: CTO",
                        "    team: executive",
                        "    manager: hl_ceo",
                        "    expertise: Technical lead",
                        "  hl_backend_engineer:",
                        "    command: hl_backend_engineer",
                        "    title: Backend Engineer",
                        "    team: engineering",
                        "    manager: hl_cto",
                        "    expertise: Backend",
                        "routing: strict_hierarchical",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["org", "graph", "--org", str(org)])

        self.assertEqual(exit_code, 0)
        self.assertIn("routing: strict_hierarchical", output.getvalue())
        self.assertIn("`-- hl_ceo: CEO", output.getvalue())
        self.assertIn("`-- hl_backend_engineer: Backend Engineer", output.getvalue())

    def test_agents_command_can_run_health_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            org = root / "config" / "org.yaml"
            org.parent.mkdir()
            org.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "    expertise: Coordinator",
                    ]
                ),
                encoding="utf-8",
            )
            output = io.StringIO()

            with (
                mock.patch("sys.stdout", output),
                mock.patch("hermes_link.cli.inspect_agent") as inspect,
                mock.patch("hermes_link.cli.check_agent_health") as health,
            ):
                inspect.return_value.command_available = True
                inspect.return_value.skill_installed = True
                inspect.return_value.plugin_installed = True
                inspect.return_value.plugin_enabled = True
                inspect.return_value.agent.command = "hl_ceo"
                inspect.return_value.agent.expertise = "Coordinator"
                health.return_value.ok = True
                health.return_value.response = "HERMES_LINK_HEALTH_OK"
                health.return_value.error = ""
                health.return_value.elapsed_seconds = 0.1
                exit_code = main(["agents", "--org", str(org), "--check"])

        self.assertEqual(exit_code, 0)
        self.assertIn("health: ok", output.getvalue())
        self.assertIn("HERMES_LINK_HEALTH_OK", output.getvalue())

    def test_doctor_command_returns_failure_for_failed_check(self) -> None:
        output = io.StringIO()

        with (
            mock.patch("sys.stdout", output),
            mock.patch("hermes_link.cli.run_doctor") as doctor,
        ):
            doctor.return_value = [SimpleNamespace(ok=False, name="org config", detail="missing")]
            exit_code = main(["doctor"])

        self.assertEqual(exit_code, 1)
        self.assertIn("FAIL org config: missing", output.getvalue())


if __name__ == "__main__":
    unittest.main()
