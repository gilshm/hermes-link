import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hermes_link.directive import SendDirective, parse_send_directive
from hermes_link.hermes_runner import HermesRunner
from hermes_link.message import Message
from hermes_link.org import load_org


class AgentCommsTests(unittest.TestCase):
    def test_parse_send_directive(self) -> None:
        self.assertEqual(
            parse_send_directive("SEND agent_b: hello there"),
            SendDirective("agent_b", "hello there"),
        )
        self.assertEqual(
            parse_send_directive("SEND @review: hello there"),
            SendDirective("@review", "hello there"),
        )
        self.assertIsNone(parse_send_directive("hello user"))

    def test_load_org(self) -> None:
        org = load_org(Path("config/org.yaml"))

        self.assertEqual(set(org.agents), {"agent_a", "agent_b"})
        self.assertEqual(org.agents["agent_a"].command, "agent_a")
        self.assertIn("coordinator", org.agents["agent_a"].expertise)
        self.assertIn("Second-opinion", org.agents["agent_b"].expertise)
        self.assertEqual(org.resolve_agent("@review"), "agent_b")
        self.assertEqual(org.skill_path.name, "SKILL.md")

    def test_runner_routes_send_directives_and_reuses_agent_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND agent_id: message.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  agent_a:",
                        "    command: agent_a",
                        "  agent_b:",
                        "    command: agent_b",
                        "skill: skills/agent-comms/SKILL.md",
                        "max_messages: 6",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            calls: list[list[str]] = []
            outputs = [
                "session_id: session-a\nSEND agent_b: one",
                "session_id: session-b\nSEND agent_a: two",
                "session_id: session-a\nfinal answer",
            ]

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, stdout=outputs.pop(0), stderr="")

            with mock.patch("subprocess.run", side_effect=fake_run):
                result = HermesRunner(org, cwd=root).chat("agent_a", "start")

        self.assertEqual(
            result.transcript,
            [
                Message("user", "agent_a", "start"),
                Message("agent_a", "agent_b", "one"),
                Message("agent_b", "agent_a", "two"),
            ],
        )
        self.assertEqual(result.final_response, "final answer")
        self.assertNotIn("-r", calls[0])
        self.assertNotIn("-r", calls[1])
        self.assertIn("-r", calls[2])
        self.assertEqual(calls[2][calls[2].index("-r") + 1], "session-a")

    def test_runner_stops_when_directive_targets_stop_recipient(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND agent_id: message.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  agent_a:",
                        "    command: agent_a",
                        "  agent_b:",
                        "    command: agent_b",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            calls: list[list[str]] = []

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, stdout="session_id: session-b\nSEND agent_a: reply", stderr="")

            with mock.patch("subprocess.run", side_effect=fake_run):
                result = HermesRunner(org, cwd=root).chat(
                    "agent_b",
                    "start",
                    stop_recipient="agent_a",
                )

        self.assertEqual(result.transcript, [Message("user", "agent_b", "start"), Message("agent_b", "agent_a", "reply")])
        self.assertEqual(result.final_response, "reply")
        self.assertEqual(len(calls), 1)

    def test_runner_rejects_repeated_routed_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND agent_id: message.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  agent_a:",
                        "    command: agent_a",
                        "  agent_b:",
                        "    command: agent_b",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            outputs = [
                "session_id: session-a\nSEND agent_b: same message",
                "session_id: session-b\nSEND agent_a: other message",
                "session_id: session-a\nSEND agent_b:  SAME   message ",
            ]

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 0, stdout=outputs.pop(0), stderr="")

            with (
                mock.patch("subprocess.run", side_effect=fake_run),
                self.assertRaisesRegex(RuntimeError, "repeated routed message"),
            ):
                HermesRunner(org, cwd=root).chat("agent_a", "start")

    def test_runner_can_request_one_send_directive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND agent_id: message.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  agent_a:",
                        "    command: agent_a",
                        "  agent_b:",
                        "    command: agent_b",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 0, stdout="session_id: session-a\nSEND agent_b: hello", stderr="")

            with mock.patch("subprocess.run", side_effect=fake_run):
                routed = HermesRunner(org, cwd=root).request_send("agent_a", "say hello")

        self.assertEqual(routed.message, Message("agent_a", "agent_b", "hello"))
        self.assertEqual(routed.turn.session_id, "session-a")

    def test_runner_rejects_missing_agent_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND agent_id: message.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  agent_a:",
                        "    command: missing-agent-a",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)

            with self.assertRaisesRegex(RuntimeError, "agent command not found"):
                HermesRunner(org, cwd=root).request_send("agent_a", "hello")

    def test_runner_resolves_topic_send_directive_to_default_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND agent_id: message.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  agent_a:",
                        "    command: agent_a",
                        "  agent_b:",
                        "    command: agent_b",
                        "topics:",
                        "  review:",
                        "    default: agent_b",
                        "    agents:",
                        "      - agent_b",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 0, stdout="session_id: session-a\nSEND @review: hello", stderr="")

            with mock.patch("subprocess.run", side_effect=fake_run):
                routed = HermesRunner(org, cwd=root).request_send("agent_a", "say hello")

        self.assertEqual(routed.message, Message("agent_a", "agent_b", "hello"))

    def test_runner_includes_agent_expertise_in_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND agent_id: message.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  agent_a:",
                        "    command: agent_a",
                        "    expertise: Coordinator",
                        "  agent_b:",
                        "    command: agent_b",
                        "    expertise: Review specialist",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            prompts: list[str] = []

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                prompts.append(args[-1])
                return subprocess.CompletedProcess(args, 0, stdout="session_id: session-a\nSEND agent_b: hello", stderr="")

            with mock.patch("subprocess.run", side_effect=fake_run):
                HermesRunner(org, cwd=root).request_send("agent_a", "say hello")

        self.assertIn("- agent_a: Coordinator", prompts[0])
        self.assertIn("- agent_b: Review specialist", prompts[0])


if __name__ == "__main__":
    unittest.main()
