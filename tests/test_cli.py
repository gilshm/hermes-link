import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_link.cli import main
from hermes_link.hermes_runner import AgentTurn, ChatResult
from hermes_link.log import EventLog
from hermes_link.message import Message


class CliTests(unittest.TestCase):
    def test_log_command_prints_formatted_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            EventLog(path).write("message", thread_id="thread-1", from_agent="agent_a", to_agent="agent_b", body="hello")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["log", "--path", str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("[thread-1] ├─ agent_a -> agent_b: hello", output.getvalue())

    def test_log_command_can_force_color(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            EventLog(path).write("message", thread_id="thread-1", from_agent="agent_a", to_agent="agent_b", body="hello")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["log", "--path", str(path), "--color", "always"])

        self.assertEqual(exit_code, 0)
        self.assertIn("\033[", output.getvalue())

    def test_trace_command_prints_matching_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            EventLog(path).write("message", thread_id="thread-1", from_agent="agent_a", to_agent="agent_b", body="hello")
            EventLog(path).write("message", thread_id="thread-2", from_agent="agent_a", to_agent="agent_b", body="ignore")
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
            path.write_text('{"source-a:agent_b": "session-b"}', encoding="utf-8")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["sessions", "--path", str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("source-a -> agent_b: session-b", output.getvalue())

    def test_chat_command_labels_final_routed_reply(self) -> None:
        output = io.StringIO()
        result = ChatResult(
            transcript=[
                Message("user", "agent_a", "start"),
                Message("agent_a", "agent_b", "ping"),
            ],
            turns=[
                AgentTurn("agent_a", "session-a", "SEND agent_b: ping"),
                AgentTurn("agent_b", "session-b", "pong"),
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
            exit_code = main(["chat", "agent_a", "start"])

        self.assertEqual(exit_code, 0)
        self.assertIn("agent_a -> agent_b: ping", output.getvalue())
        self.assertIn("agent_b -> agent_a: pong", output.getvalue())

    def test_org_validate_command_reports_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
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
            skill = root / "skills" / "agent-comms" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("skill", encoding="utf-8")
            plugin = root / ".hermes" / "plugins" / "hermes-link" / "plugin.yaml"
            plugin.parent.mkdir(parents=True)
            plugin.write_text("name: hermes-link", encoding="utf-8")
            output = io.StringIO()

            with (
                mock.patch("sys.stdout", output),
                mock.patch("hermes_link.validation.shutil.which", return_value="/bin/agent_a"),
                mock.patch("hermes_link.cli.REPO_ROOT", root),
            ):
                exit_code = main(["org", "validate", "--org", str(org)])

        self.assertEqual(exit_code, 0)
        self.assertIn("org config ok", output.getvalue())


if __name__ == "__main__":
    unittest.main()
