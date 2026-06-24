import io
import os
import tempfile
import time
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

    def test_log_command_can_truncate_message_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            EventLog(path).write("message", thread_id="thread-1", from_agent="hl_ceo", to_agent="hl_advisor", body="abcdefghijklmnopqrstuvwxyz")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["log", "--path", str(path), "--max-body-chars", "5"])

        self.assertEqual(exit_code, 0)
        self.assertIn("abcde...", output.getvalue())
        self.assertNotIn("fghijklmnopqrstuvwxyz", output.getvalue())

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

    def test_trace_command_can_truncate_message_bodies(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            EventLog(path).write("message", thread_id="thread-1", from_agent="hl_ceo", to_agent="hl_advisor", body="abcdefghijklmnopqrstuvwxyz")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["trace", "thread-1", "--path", str(path), "--max-body-chars", "7"])

        self.assertEqual(exit_code, 0)
        self.assertIn("abcdefg...", output.getvalue())
        self.assertNotIn("hijklmnopqrstuvwxyz", output.getvalue())

    def test_trace_command_can_print_mermaid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            EventLog(path).write("message", thread_id="thread-1", from_agent="hl_ceo", to_agent="hl_advisor", body="hello")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["trace", "thread-1", "--path", str(path), "--format", "mermaid"])

        self.assertEqual(exit_code, 0)
        self.assertIn("sequenceDiagram", output.getvalue())
        self.assertIn("hl_ceo->>hl_advisor: hello", output.getvalue())

    def test_sessions_command_prints_session_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "session-map.json"
            path.write_text('{"source-a:hl_advisor": "session-b"}', encoding="utf-8")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["sessions", "--path", str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("source-a -> hl_advisor: session-b", output.getvalue())

    def test_sessions_command_can_filter_by_thread_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            log = EventLog(path)
            log.write(
                "message",
                thread_id="thread-a",
                from_agent="hl_ceo",
                to_agent="hl_advisor",
                from_session_id="session-ceo",
                to_session_id="session-advisor",
                body="hello",
            )
            log.write("final", thread_id="thread-b", agent="hl_cto", session_id="ignore", body="ignore")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(["sessions", "--thread", "thread-a", "--log-path", str(path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("Sessions for thread thread-a", output.getvalue())
        self.assertIn("hl_ceo: session-ceo", output.getvalue())
        self.assertIn("hl_advisor: session-advisor", output.getvalue())
        self.assertNotIn("ignore", output.getvalue())

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
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "events.jsonl"

            with (
                mock.patch("sys.stdout", output),
                mock.patch("hermes_link.cli.load_org"),
                mock.patch("hermes_link.cli.HermesRunner") as runner,
            ):
                runner.return_value.chat.return_value = result
                exit_code = main(["chat", "hl_ceo", "start", "--thread-id", "thread-test", "--log-path", str(log_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("thread_id: thread-test", output.getvalue())
        self.assertIn("hl_ceo -> hl_advisor: ping", output.getvalue())
        self.assertIn("hl_advisor -> hl_ceo: pong", output.getvalue())

    def test_cleanup_removes_old_locks_and_rotates_large_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_dir = Path(tmpdir) / "state"
            locks = state_dir / "locks"
            locks.mkdir(parents=True)
            old_lock = locks / "old.lock"
            fresh_lock = locks / "fresh.lock"
            old_lock.write_text("", encoding="utf-8")
            fresh_lock.write_text("", encoding="utf-8")
            old_time = time.time() - 10
            os.utime(old_lock, (old_time, old_time))
            log_path = state_dir / "events.jsonl"
            log_path.write_text("x" * 20, encoding="utf-8")
            output = io.StringIO()

            with mock.patch("sys.stdout", output):
                exit_code = main(
                    [
                        "cleanup",
                        "--state-dir",
                        str(state_dir),
                        "--log-path",
                        str(log_path),
                        "--lock-older-than-seconds",
                        "5",
                        "--max-log-bytes",
                        "10",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertFalse(old_lock.exists())
            self.assertTrue(fresh_lock.exists())
            self.assertFalse(log_path.exists())
            self.assertTrue((state_dir / "events.jsonl.1").exists())
            self.assertIn("removed locks: 1", output.getvalue())
            self.assertIn("rotated log:", output.getvalue())

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
                        "    capabilities:",
                        "      - architecture",
                        "    expertise: Technical lead",
                        "  hl_backend_engineer:",
                        "    command: hl_backend_engineer",
                        "    title: Backend Engineer",
                        "    team: engineering",
                        "    manager: hl_cto",
                        "    capabilities:",
                        "      - api",
                        "      - services",
                        "    expertise: Backend",
                        "groups:",
                        "  engineering:",
                        "    - hl_backend_engineer",
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
        self.assertIn("capabilities=architecture", output.getvalue())
        self.assertIn("`-- hl_backend_engineer: Backend Engineer (team=engineering; manager=hl_cto; capabilities=api,services)", output.getvalue())
        self.assertIn("- @engineering: hl_backend_engineer", output.getvalue())
        self.assertIn("- @direct_reports: sender's direct reports", output.getvalue())
        self.assertIn("- @peers: sender's same-manager peers", output.getvalue())

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
                        "    capabilities:",
                        "      - delegation",
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
                inspect.return_value.agent.capabilities = ("delegation",)
                health.return_value.ok = True
                health.return_value.response = "HERMES_LINK_HEALTH_OK"
                health.return_value.error = ""
                health.return_value.elapsed_seconds = 0.1
                exit_code = main(["agents", "--org", str(org), "--check"])

        self.assertEqual(exit_code, 0)
        self.assertIn("capabilities: delegation", output.getvalue())
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

    def test_doctor_command_can_print_route_matrix(self) -> None:
        output = io.StringIO()

        with (
            mock.patch("sys.stdout", output),
            mock.patch("hermes_link.cli.run_doctor") as doctor,
        ):
            doctor.return_value = [
                SimpleNamespace(ok=True, name="route hl_advisor -> hl_backend_engineer", detail="blocked by policy"),
                SimpleNamespace(ok=True, name="route hl_advisor -> hl_ceo", detail="allowed"),
            ]
            exit_code = main(["doctor", "--route-matrix", "--route-from", "hl_advisor"])

        self.assertEqual(exit_code, 0)
        doctor.assert_called_once()
        self.assertTrue(doctor.call_args.kwargs["route_matrix"])
        self.assertEqual(doctor.call_args.kwargs["route_from"], "hl_advisor")
        self.assertIn("OK route hl_advisor -> hl_backend_engineer: blocked by policy", output.getvalue())


if __name__ == "__main__":
    unittest.main()
