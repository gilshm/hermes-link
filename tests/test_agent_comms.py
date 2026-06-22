import concurrent.futures
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from hermes_link.directive import SendAllDirective, SendDirective, parse_send_directive
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

    def test_parse_send_all_directive(self) -> None:
        self.assertEqual(
            parse_send_directive(
                "\n".join(
                    [
                        "SEND_ALL:",
                        "- hl_backend_engineer: API check",
                        "- hl_frontend_engineer: UI check",
                    ]
                )
            ),
            SendAllDirective(
                (
                    SendDirective("hl_backend_engineer", "API check"),
                    SendDirective("hl_frontend_engineer", "UI check"),
                )
            ),
        )

    def test_parse_compact_send_all_group_directive(self) -> None:
        self.assertEqual(
            parse_send_directive("SEND_ALL @engineering: status check"),
            SendAllDirective((SendDirective("@engineering", "status check"),)),
        )

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
        self.assertEqual(org.resolve_group("@engineering"), ("hl_backend_engineer", "hl_frontend_engineer"))
        self.assertEqual(
            org.resolve_group("@leadership"),
            ("hl_ceo", "hl_advisor", "hl_cto", "hl_product_manager"),
        )
        self.assertEqual(
            org.resolve_broadcast("hl_cto", "@direct_reports"),
            ("hl_backend_engineer", "hl_frontend_engineer"),
        )
        self.assertEqual(org.resolve_broadcast("hl_backend_engineer", "@manager"), ("hl_cto",))
        self.assertEqual(org.resolve_broadcast("hl_backend_engineer", "@peers"), ("hl_frontend_engineer",))
        self.assertEqual(org.resolve_broadcast("hl_backend_engineer", "@team"), ("hl_frontend_engineer",))
        self.assertEqual(org.resolve_broadcast("hl_ceo", "@manager"), ())
        self.assertEqual(org.skill_path.name, "SKILL.md")
        self.assertEqual(org.scatter_timeout, 120)

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

    def test_runner_keeps_parallel_conversations_isolated(self) -> None:
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
            lock = threading.Lock()
            calls_by_run = {"RUN_A": [], "RUN_B": []}

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                prompt = args[-1]
                run_id = "RUN_A" if "RUN_A" in prompt else "RUN_B"
                agent = args[0]
                with lock:
                    calls_by_run[run_id].append(args)
                    call_number = len(calls_by_run[run_id])
                if agent == "hl_ceo" and call_number == 1:
                    stdout = f"session_id: ceo-{run_id}\nSEND hl_advisor: {run_id} delegated"
                elif agent == "hl_advisor":
                    stdout = f"session_id: advisor-{run_id}\n{run_id} advisor answer"
                else:
                    stdout = f"session_id: ceo-{run_id}\n{run_id} final answer"
                return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

            def run_conversation(run_id: str) -> object:
                runner = HermesRunner(org, cwd=root)
                result = runner.chat("hl_ceo", f"start {run_id}")
                return result, runner.sessions

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
                concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor,
            ):
                futures = [executor.submit(run_conversation, run_id) for run_id in ("RUN_A", "RUN_B")]
                results = [future.result(timeout=5) for future in futures]

        by_run = {result.final_response.split()[0]: (result, sessions) for result, sessions in results}
        self.assertEqual(set(by_run), {"RUN_A", "RUN_B"})
        for run_id, (result, sessions) in by_run.items():
            other_run = "RUN_B" if run_id == "RUN_A" else "RUN_A"
            self.assertEqual(result.final_response, f"{run_id} final answer")
            self.assertEqual(
                result.transcript,
                [
                    Message("user", "hl_ceo", f"start {run_id}"),
                    Message("hl_ceo", "hl_advisor", f"{run_id} delegated"),
                    Message("hl_advisor", "hl_ceo", f"{run_id} advisor answer"),
                ],
            )
            self.assertEqual(sessions["hl_ceo"], f"ceo-{run_id}")
            self.assertEqual(sessions["hl_advisor"], f"advisor-{run_id}")
            self.assertNotIn(other_run, " ".join(message.body for message in result.transcript))

    def test_runner_keeps_parallel_employee_sets_isolated(self) -> None:
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
                        "  hl_cto:",
                        "    command: hl_cto",
                        "  hl_backend_engineer:",
                        "    command: hl_backend_engineer",
                        "  hl_product_manager:",
                        "    command: hl_product_manager",
                        "  hl_frontend_engineer:",
                        "    command: hl_frontend_engineer",
                        "skill: skills/agent-comms/SKILL.md",
                        "max_messages: 4",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            lock = threading.Lock()
            calls_by_run = {"EXEC_RUN": [], "ENG_RUN": [], "PRODUCT_RUN": []}

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                prompt = args[-1]
                if "EXEC_RUN" in prompt:
                    run_id = "EXEC_RUN"
                elif "ENG_RUN" in prompt:
                    run_id = "ENG_RUN"
                else:
                    run_id = "PRODUCT_RUN"
                agent = args[0]
                with lock:
                    calls_by_run[run_id].append(args)
                    call_number = len(calls_by_run[run_id])
                if run_id == "EXEC_RUN":
                    stdout = (
                        "session_id: exec-ceo\nSEND hl_advisor: EXEC_RUN delegated"
                        if call_number == 1
                        else f"session_id: exec-advisor\nEXEC_RUN advisor answer"
                    )
                    if agent == "hl_ceo" and call_number == 3:
                        stdout = "session_id: exec-ceo\nEXEC_RUN final answer"
                elif run_id == "ENG_RUN":
                    if call_number == 1:
                        stdout = "session_id: eng-cto\nSEND hl_backend_engineer: ENG_RUN delegated"
                    elif agent == "hl_backend_engineer":
                        stdout = "session_id: eng-backend\nENG_RUN backend answer"
                    else:
                        stdout = "session_id: eng-cto\nENG_RUN final answer"
                elif call_number == 1:
                    stdout = "session_id: product-pm\nSEND hl_frontend_engineer: PRODUCT_RUN delegated"
                elif agent == "hl_frontend_engineer":
                    stdout = "session_id: product-frontend\nPRODUCT_RUN frontend answer"
                else:
                    stdout = "session_id: product-pm\nPRODUCT_RUN final answer"
                return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

            conversations = [
                ("EXEC_RUN", "hl_ceo"),
                ("ENG_RUN", "hl_cto"),
                ("PRODUCT_RUN", "hl_product_manager"),
            ]

            def run_conversation(run_id: str, sender: str) -> object:
                runner = HermesRunner(org, cwd=root)
                result = runner.chat(sender, f"start {run_id}")
                return result, runner.sessions

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
                concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor,
            ):
                futures = [
                    executor.submit(run_conversation, run_id, sender)
                    for run_id, sender in conversations
                ]
                results = [future.result(timeout=5) for future in futures]

        by_run = {result.final_response.split()[0]: (result, sessions) for result, sessions in results}
        self.assertEqual(set(by_run), {"EXEC_RUN", "ENG_RUN", "PRODUCT_RUN"})
        exec_result, exec_sessions = by_run["EXEC_RUN"]
        eng_result, eng_sessions = by_run["ENG_RUN"]
        product_result, product_sessions = by_run["PRODUCT_RUN"]
        self.assertEqual(
            [(message.sender, message.recipient) for message in exec_result.transcript],
            [("user", "hl_ceo"), ("hl_ceo", "hl_advisor"), ("hl_advisor", "hl_ceo")],
        )
        self.assertEqual(
            [(message.sender, message.recipient) for message in eng_result.transcript],
            [("user", "hl_cto"), ("hl_cto", "hl_backend_engineer"), ("hl_backend_engineer", "hl_cto")],
        )
        self.assertEqual(
            [(message.sender, message.recipient) for message in product_result.transcript],
            [
                ("user", "hl_product_manager"),
                ("hl_product_manager", "hl_frontend_engineer"),
                ("hl_frontend_engineer", "hl_product_manager"),
            ],
        )
        self.assertEqual(exec_sessions, {"hl_ceo": "exec-ceo", "hl_advisor": "exec-advisor"})
        self.assertEqual(eng_sessions, {"hl_cto": "eng-cto", "hl_backend_engineer": "eng-backend"})
        self.assertEqual(
            product_sessions,
            {"hl_product_manager": "product-pm", "hl_frontend_engineer": "product-frontend"},
        )
        self.assertNotIn("ENG_RUN", " ".join(message.body for message in exec_result.transcript))
        self.assertNotIn("PRODUCT_RUN", " ".join(message.body for message in exec_result.transcript))
        self.assertNotIn("EXEC_RUN", " ".join(message.body for message in eng_result.transcript))
        self.assertNotIn("PRODUCT_RUN", " ".join(message.body for message in eng_result.transcript))
        self.assertNotIn("EXEC_RUN", " ".join(message.body for message in product_result.transcript))
        self.assertNotIn("ENG_RUN", " ".join(message.body for message in product_result.transcript))

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

    def test_runner_handles_send_all_scatter_gather(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND_ALL.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  hl_cto:",
                        "    command: hl_cto",
                        "  hl_backend_engineer:",
                        "    command: hl_backend_engineer",
                        "  hl_frontend_engineer:",
                        "    command: hl_frontend_engineer",
                        "skill: skills/agent-comms/SKILL.md",
                        "max_messages: 3",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            outputs = {
                "hl_cto": [
                    "session_id: cto-session\nSEND_ALL:\n- hl_backend_engineer: backend status\n- hl_frontend_engineer: frontend status",
                    "session_id: cto-session\nBoth reports replied.",
                ],
                "hl_backend_engineer": ["session_id: backend-session\nBackend ready."],
                "hl_frontend_engineer": ["session_id: frontend-session\nFrontend ready."],
            }

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                return subprocess.CompletedProcess(args, 0, stdout=outputs[args[0]].pop(0), stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                runner = HermesRunner(org, cwd=root)
                result = runner.chat("hl_cto", "ask reports")

        self.assertEqual(result.final_response, "Both reports replied.")
        self.assertEqual(
            [(message.sender, message.recipient) for message in result.transcript],
            [
                ("user", "hl_cto"),
                ("hl_cto", "hl_backend_engineer"),
                ("hl_cto", "hl_frontend_engineer"),
            ],
        )
        self.assertEqual(runner.sessions["hl_cto"], "cto-session")

    def test_runner_expands_group_send_all_through_scatter_gather(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND_ALL @group: message.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  hl_cto:",
                        "    command: hl_cto",
                        "  hl_backend_engineer:",
                        "    command: hl_backend_engineer",
                        "  hl_frontend_engineer:",
                        "    command: hl_frontend_engineer",
                        "groups:",
                        "  engineering:",
                        "    - hl_backend_engineer",
                        "    - hl_frontend_engineer",
                        "skill: skills/agent-comms/SKILL.md",
                        "max_messages: 3",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            outputs = {
                "hl_cto": [
                    "session_id: cto-session\nSEND_ALL @engineering: team status",
                    "session_id: cto-session\nEngineering replied.",
                ],
                "hl_backend_engineer": ["session_id: backend-session\nBackend replied."],
                "hl_frontend_engineer": ["session_id: frontend-session\nFrontend replied."],
            }
            prompts = []

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                prompts.append(args[-1])
                return subprocess.CompletedProcess(args, 0, stdout=outputs[args[0]].pop(0), stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                runner = HermesRunner(org, cwd=root)
                result = runner.chat("hl_cto", "ask engineering")

        self.assertEqual(result.final_response, "Engineering replied.")
        self.assertEqual(
            [(message.sender, message.recipient, message.body) for message in result.transcript],
            [
                ("user", "hl_cto", "ask engineering"),
                ("hl_cto", "hl_backend_engineer", "team status"),
                ("hl_cto", "hl_frontend_engineer", "team status"),
            ],
        )
        self.assertIn("hl_backend_engineer replied: Backend replied.", prompts[-1])
        self.assertIn("hl_frontend_engineer replied: Frontend replied.", prompts[-1])
        self.assertEqual(runner.sessions["hl_cto"], "cto-session")

    def test_runner_expands_built_in_direct_reports_send_all_through_scatter_gather(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND_ALL @direct_reports: message.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  hl_cto:",
                        "    command: hl_cto",
                        "  hl_backend_engineer:",
                        "    command: hl_backend_engineer",
                        "    manager: hl_cto",
                        "  hl_frontend_engineer:",
                        "    command: hl_frontend_engineer",
                        "    manager: hl_cto",
                        "skill: skills/agent-comms/SKILL.md",
                        "max_messages: 3",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            outputs = {
                "hl_cto": [
                    "session_id: cto-session\nSEND_ALL @direct_reports: report status",
                    "session_id: cto-session\nDirect reports replied.",
                ],
                "hl_backend_engineer": ["session_id: backend-session\nBackend replied."],
                "hl_frontend_engineer": ["session_id: frontend-session\nFrontend replied."],
            }
            prompts = []

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                prompts.append(args[-1])
                return subprocess.CompletedProcess(args, 0, stdout=outputs[args[0]].pop(0), stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                runner = HermesRunner(org, cwd=root)
                result = runner.chat("hl_cto", "ask direct reports")

        self.assertEqual(result.final_response, "Direct reports replied.")
        self.assertEqual(
            [(message.sender, message.recipient, message.body) for message in result.transcript],
            [
                ("user", "hl_cto", "ask direct reports"),
                ("hl_cto", "hl_backend_engineer", "report status"),
                ("hl_cto", "hl_frontend_engineer", "report status"),
            ],
        )
        self.assertIn("hl_backend_engineer replied: Backend replied.", prompts[-1])
        self.assertIn("hl_frontend_engineer replied: Frontend replied.", prompts[-1])

    def test_runner_expands_manager_peers_and_team_broadcasts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND_ALL @target: message.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  hl_cto:",
                        "    command: hl_cto",
                        "    team: executive",
                        "  hl_backend_engineer:",
                        "    command: hl_backend_engineer",
                        "    team: engineering",
                        "    manager: hl_cto",
                        "  hl_frontend_engineer:",
                        "    command: hl_frontend_engineer",
                        "    team: engineering",
                        "    manager: hl_cto",
                        "skill: skills/agent-comms/SKILL.md",
                        "max_messages: 3",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)

        self.assertEqual(org.resolve_broadcast("hl_backend_engineer", "@manager"), ("hl_cto",))
        self.assertEqual(org.resolve_broadcast("hl_backend_engineer", "@peers"), ("hl_frontend_engineer",))
        self.assertEqual(org.resolve_broadcast("hl_backend_engineer", "@team"), ("hl_frontend_engineer",))

    def test_runner_reports_empty_built_in_broadcast_as_scatter_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND_ALL @manager: message.", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "skill: skills/agent-comms/SKILL.md",
                        "max_messages: 3",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            outputs = {
                "hl_ceo": [
                    "session_id: ceo-session\nSEND_ALL @manager: need advice",
                    "session_id: ceo-session\nI have no manager.",
                ],
            }
            prompts = []

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                prompts.append(args[-1])
                return subprocess.CompletedProcess(args, 0, stdout=outputs[args[0]].pop(0), stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                result = HermesRunner(org, cwd=root).chat("hl_ceo", "ask manager")

        self.assertEqual(result.final_response, "I have no manager.")
        self.assertIn("@manager failed: @manager resolved to no recipients.", prompts[-1])
        self.assertEqual(len(result.transcript), 1)

    def test_runner_send_all_continues_after_blocked_recipient(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("Use SEND_ALL.", encoding="utf-8")
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
                        "max_messages: 3",
                    ]
                ),
                encoding="utf-8",
            )
            org = load_org(org_path)
            prompts = []
            outputs = {
                "hl_advisor": [
                    "session_id: advisor-session\nSEND_ALL:\n- hl_cto: executive peer check\n- hl_backend_engineer: blocked check",
                    "session_id: advisor-session\nI got the CTO reply and one blocked route.",
                ],
                "hl_cto": ["session_id: cto-session\nCTO replied."],
            }

            def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                prompts.append(args[-1])
                return subprocess.CompletedProcess(args, 0, stdout=outputs[args[0]].pop(0), stderr="")

            with (
                mock.patch("hermes_link.hermes_runner.shutil.which", return_value="/bin/hermes"),
                mock.patch("subprocess.run", side_effect=fake_run),
            ):
                result = HermesRunner(org, cwd=root).chat("hl_advisor", "ask both")

        self.assertEqual(result.final_response, "I got the CTO reply and one blocked route.")
        self.assertIn("hl_cto replied: CTO replied.", prompts[-1])
        self.assertIn("hl_backend_engineer failed:", prompts[-1])

    def test_routing_policy_defaults_to_flat_org(self) -> None:
        org = load_org(Path("config/org.yaml"))

        self.assertTrue(org.can_route("hl_backend_engineer", "hl_ceo"))
        self.assertTrue(org.can_route("hl_frontend_engineer", "hl_advisor"))

    def test_group_cannot_use_built_in_broadcast_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            skill_path = root / "skills" / "agent-comms" / "SKILL.md"
            skill_path.parent.mkdir(parents=True)
            skill_path.write_text("skill", encoding="utf-8")
            org_path = root / "config" / "org.yaml"
            org_path.parent.mkdir()
            org_path.write_text(
                "\n".join(
                    [
                        "agents:",
                        "  hl_ceo:",
                        "    command: hl_ceo",
                        "groups:",
                        "  direct_reports:",
                        "    - hl_ceo",
                        "skill: skills/agent-comms/SKILL.md",
                    ]
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "conflicts with built-in broadcast target"):
                load_org(org_path)

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
