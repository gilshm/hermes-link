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
            parse_send_directive("SEND hl_advisor: hello there"),
            SendDirective("hl_advisor", "hello there"),
        )
        self.assertEqual(
            parse_send_directive("SEND @review: hello there"),
            SendDirective("@review", "hello there"),
        )
        self.assertIsNone(parse_send_directive("hello user"))

    def test_load_org(self) -> None:
        org = load_org(Path("config/org.yaml"))

        self.assertEqual(
            set(org.agents),
            {"hl_ceo", "hl_advisor", "hl_cto", "hl_product_manager", "hl_backend_engineer", "hl_frontend_engineer"},
        )
        self.assertEqual(org.agents["hl_ceo"].command, "hl_ceo")
        self.assertEqual(org.agents["hl_ceo"].title, "CEO")
        self.assertEqual(org.agents["hl_advisor"].manager, "hl_ceo")
        self.assertEqual(org.agents["hl_backend_engineer"].team, "engineering")
        self.assertIn("decision maker", org.agents["hl_ceo"].expertise)
        self.assertIn("second opinions", org.agents["hl_advisor"].expertise)
        self.assertEqual(org.resolve_agent("@review"), "hl_advisor")
        self.assertEqual(org.resolve_agent("@technical"), "hl_cto")
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
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "  hl_advisor:",
                        "    command: hl_advisor",
                        "skill: skills/agent-comms/SKILL.md",
                        "max_messages: 6",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            calls: list[list[str]] = []
            outputs = [
                "session_id: session-a\nSEND hl_advisor: one",
                "session_id: session-b\nSEND hl_ceo: two",
                "session_id: session-a\nfinal answer",
            ]

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, stdout=outputs.pop(0), stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                result = HermesRunner(org, cwd=root).chat("hl_ceo", "start")

        self.assertEqual(
            result.transcript,
            [
                Message("user", "hl_ceo", "start"),
                Message("hl_ceo", "hl_advisor", "one"),
                Message("hl_advisor", "hl_ceo", "two"),
            ],
        )
        self.assertEqual(result.final_response, "final answer")
        self.assertNotIn("-r", calls[0])
        self.assertNotIn("-r", calls[1])
        self.assertIn("-r", calls[2])
        self.assertEqual(calls[2][calls[2].index("-r") + 1], "session-a")

    def test_runner_returns_recipient_reply_to_origin_agent_for_final_answer(self) -> None:
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
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "  hl_advisor:",
                        "    command: hl_advisor",
                        "skill: skills/agent-comms/SKILL.md",
                        "max_messages: 4",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            calls: list[list[str]] = []
            outputs = [
                "session_id: session-a\nSEND hl_advisor: ping",
                "session_id: session-b\npong",
                "session_id: session-a\nfinal to user",
            ]

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, stdout=outputs.pop(0), stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                result = HermesRunner(org, cwd=root).chat("hl_ceo", "start")

        self.assertEqual(
            result.transcript,
            [
                Message("user", "hl_ceo", "start"),
                Message("hl_ceo", "hl_advisor", "ping"),
                Message("hl_advisor", "hl_ceo", "pong"),
            ],
        )
        self.assertEqual(result.final_response, "final to user")
        self.assertEqual(calls[2][0], "hl_ceo")
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
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "  hl_advisor:",
                        "    command: hl_advisor",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            calls: list[list[str]] = []

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, stdout="session_id: session-b\nSEND hl_ceo: reply", stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                result = HermesRunner(org, cwd=root).chat(
                    "hl_advisor",
                    "start",
                    stop_recipient="hl_ceo",
                )

        self.assertEqual(result.transcript, [Message("user", "hl_advisor", "start"), Message("hl_advisor", "hl_ceo", "reply")])
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
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "  hl_advisor:",
                        "    command: hl_advisor",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            outputs = [
                "session_id: session-a\nSEND hl_advisor: same message",
                "session_id: session-b\nSEND hl_ceo: other message",
                "session_id: session-a\nSEND hl_advisor:  SAME   message ",
            ]

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 0, stdout=outputs.pop(0), stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
                self.assertRaisesRegex(RuntimeError, "repeated routed message"),
            ):
                HermesRunner(org, cwd=root).chat("hl_ceo", "start")

    def test_runner_notifies_sender_when_policy_blocks_route(self) -> None:
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
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "  hl_advisor:",
                        "    command: hl_advisor",
                        "    manager: hl_ceo",
                        "  hl_cto:",
                        "    command: hl_cto",
                        "    manager: hl_ceo",
                        "  hl_backend_engineer:",
                        "    command: hl_backend_engineer",
                        "    manager: hl_cto",
                        "routing: strict_hierarchical",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            calls: list[list[str]] = []

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                calls.append(args)
                return subprocess.CompletedProcess(args, 0, stdout="session_id: session-a\nSEND hl_backend_engineer: secret", stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                result = HermesRunner(org, cwd=root).chat("hl_advisor", "start")

        self.assertEqual(len(calls), 1)
        self.assertIn("routing policy blocked", result.final_response)
        self.assertIn("hl_advisor is not allowed to send messages to hl_backend_engineer", result.final_response)
        self.assertEqual(result.transcript, [Message("user", "hl_advisor", "start")])

    def test_routing_policy_can_use_strict_hierarchy(self) -> None:
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
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "  hl_advisor:",
                        "    command: hl_advisor",
                        "    manager: hl_ceo",
                        "  hl_cto:",
                        "    command: hl_cto",
                        "    manager: hl_ceo",
                        "  hl_backend_engineer:",
                        "    command: hl_backend_engineer",
                        "    manager: hl_cto",
                        "  hl_frontend_engineer:",
                        "    command: hl_frontend_engineer",
                        "    manager: hl_cto",
                        "routing: strict_hierarchical",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)

        self.assertTrue(org.can_route("hl_ceo", "hl_advisor"))
        self.assertTrue(org.can_route("hl_backend_engineer", "hl_ceo"))
        self.assertTrue(org.can_route("hl_advisor", "hl_cto"))
        self.assertTrue(org.can_route("hl_backend_engineer", "hl_frontend_engineer"))
        self.assertFalse(org.can_route("hl_advisor", "hl_backend_engineer"))
        self.assertFalse(org.can_route("hl_backend_engineer", "hl_advisor"))

    def test_runner_handles_strict_hierarchy_multi_hop_scenario(self) -> None:
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
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "  hl_cto:",
                        "    command: hl_cto",
                        "    manager: hl_ceo",
                        "  hl_backend_engineer:",
                        "    command: hl_backend_engineer",
                        "    manager: hl_cto",
                        "  hl_frontend_engineer:",
                        "    command: hl_frontend_engineer",
                        "    manager: hl_cto",
                        "routing: strict_hierarchical",
                        "skill: skills/agent-comms/SKILL.md",
                        "max_messages: 6",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            outputs = [
                "session_id: ceo-session\nSEND hl_cto: ask engineering",
                "session_id: cto-session\nSEND hl_backend_engineer: inspect API",
                "session_id: backend-session\nSEND hl_frontend_engineer: confirm UI contract",
                "session_id: frontend-session\nSEND hl_cto: UI contract confirmed",
                "session_id: cto-session\nSEND hl_ceo: engineering answer ready",
                "session_id: ceo-session\nfinal answer to user",
            ]

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 0, stdout=outputs.pop(0), stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                result = HermesRunner(org, cwd=root).chat("hl_ceo", "plan the feature")

        self.assertEqual(
            [(message.sender, message.recipient) for message in result.transcript],
            [
                ("user", "hl_ceo"),
                ("hl_ceo", "hl_cto"),
                ("hl_cto", "hl_backend_engineer"),
                ("hl_backend_engineer", "hl_frontend_engineer"),
                ("hl_frontend_engineer", "hl_cto"),
                ("hl_cto", "hl_ceo"),
            ],
        )
        self.assertEqual(result.final_response, "final answer to user")
        self.assertEqual(result.turns[-1].session_id, "ceo-session")

    def test_routing_policy_defaults_to_flat_org(self) -> None:
        org = load_org(Path("config/org.yaml"))

        self.assertTrue(org.can_route("hl_backend_engineer", "hl_ceo"))
        self.assertTrue(org.can_route("hl_frontend_engineer", "hl_advisor"))

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
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "  hl_advisor:",
                        "    command: hl_advisor",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 0, stdout="session_id: session-a\nSEND hl_advisor: hello", stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                routed = HermesRunner(org, cwd=root).request_send("hl_ceo", "say hello")

        self.assertEqual(routed.message, Message("hl_ceo", "hl_advisor", "hello"))
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
                        "  hl_ceo:",
                        "    command: missing-agent-a",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)

            with self.assertRaisesRegex(RuntimeError, "agent command not found"):
                HermesRunner(org, cwd=root).request_send("hl_ceo", "hello")

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
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "  hl_advisor:",
                        "    command: hl_advisor",
                        "topics:",
                        "  review:",
                        "    default: hl_advisor",
                        "    agents:",
                        "      - hl_advisor",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 0, stdout="session_id: session-a\nSEND @review: hello", stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                routed = HermesRunner(org, cwd=root).request_send("hl_ceo", "say hello")

        self.assertEqual(routed.message, Message("hl_ceo", "hl_advisor", "hello"))

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
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "    expertise: Coordinator",
                        "  hl_advisor:",
                        "    command: hl_advisor",
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
                return subprocess.CompletedProcess(args, 0, stdout="session_id: session-a\nSEND hl_advisor: hello", stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                HermesRunner(org, cwd=root).request_send("hl_ceo", "say hello")

        self.assertIn("- hl_ceo: hl_ceo. Coordinator", prompts[0])
        self.assertIn("- hl_advisor: hl_advisor. Review specialist", prompts[0])
        self.assertIn("Mode: flat. Any configured agent may contact any other configured agent.", prompts[0])


if __name__ == "__main__":
    unittest.main()
