import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from hermes_link.hermes_runner import HermesRunner
from hermes_link.org import load_org


RUN_REAL_AGENTS = os.environ.get("HERMES_LINK_RUN_REAL_AGENTS") == "1"
TIMEOUT_SECONDS = int(os.environ.get("HERMES_LINK_REAL_AGENT_TIMEOUT", "120"))
REPO_ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(RUN_REAL_AGENTS, "set HERMES_LINK_RUN_REAL_AGENTS=1")
class RealHermesAgentTests(unittest.TestCase):
    def test_user_to_hl_ceo_routes_single_message_to_advisor_through_plugin(self) -> None:
        run_id = f"HERMES_USER_PLUGIN_SINGLE_{uuid.uuid4().hex}"
        completed = _run_hl_ceo_with_plugin(
            "Use the route_message tool exactly once. Set from_agent to hl_ceo, "
            "to to hl_advisor, and body to: "
            f"{run_id} HERMES_USER_PLUGIN_SINGLE_MSG_1. "
            "After the tool returns, answer with HERMES_USER_PLUGIN_SINGLE_DONE."
        )

        self.assertNotIn("[TOOL_ERROR]", completed.stdout)
        self.assertIn("HERMES_USER_PLUGIN_SINGLE_DONE", completed.stdout)
        self.assertTrue(_recent_sessions_contain("hl_advisor", run_id, "HERMES_USER_PLUGIN_SINGLE_MSG_1"))

    def test_user_to_hl_ceo_routes_six_messages_through_plugin(self) -> None:
        run_id = f"HERMES_USER_PLUGIN_SIX_{uuid.uuid4().hex}"
        completed = _run_hl_ceo_with_plugin(
            "Use the route_message tool exactly once. Set from_agent to hl_ceo, "
            "to to hl_advisor, and max_messages to 8. The body must ask hl_advisor "
            "to conduct a six-message Hermes Link exchange using SEND directives. "
            "Count this tool-delivered body as message 1 from hl_ceo to hl_advisor, "
            f"and include {run_id} and HERMES_USER_PLUGIN_SIX_MSG_1 in that body. Then hl_advisor "
            "must SEND message 2 to hl_ceo with HERMES_USER_PLUGIN_SIX_MSG_2, "
            "hl_ceo must SEND message 3 to hl_advisor with HERMES_USER_PLUGIN_SIX_MSG_3, "
            "hl_advisor must SEND message 4 to hl_ceo with HERMES_USER_PLUGIN_SIX_MSG_4, "
            "hl_ceo must SEND message 5 to hl_advisor with HERMES_USER_PLUGIN_SIX_MSG_5, "
            "and hl_advisor must SEND message 6 to hl_ceo with HERMES_USER_PLUGIN_SIX_MSG_6. "
            "After the tool returns, answer with HERMES_USER_PLUGIN_SIX_DONE."
        )

        self.assertNotIn("[TOOL_ERROR]", completed.stdout)
        self.assertIn("HERMES_USER_PLUGIN_SIX_DONE", completed.stdout)
        self.assertTrue(_recent_sessions_contain("hl_advisor", run_id, "HERMES_USER_PLUGIN_SIX_MSG_1"))
        for index in (2, 4, 6):
            self.assertTrue(_recent_sessions_contain("hl_advisor", run_id, f"HERMES_USER_PLUGIN_SIX_MSG_{index}"))
        for index in (3, 5):
            self.assertTrue(_recent_sessions_contain("hl_ceo", run_id, f"HERMES_USER_PLUGIN_SIX_MSG_{index}"))

    def test_hl_ceo_can_route_to_advisor_through_plugin_tool(self) -> None:
        completed = _run_hl_ceo_with_plugin(
            "Use the route_message tool to send hl_advisor this exact message: "
            "HERMES_PLUGIN_TEST_PING. Then output the tool result."
        )

        self.assertTrue(completed.stdout.strip())
        self.assertNotIn("[TOOL_ERROR]", completed.stdout)

    def test_hl_ceo_can_handoff_to_cto_through_plugin_tool(self) -> None:
        run_id = f"HERMES_PLUGIN_HANDOFF_{uuid.uuid4().hex}"
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "plugin-handoff-events.jsonl"
            completed = _run_hl_ceo_with_plugin(
                "Use the route_message tool exactly once. Set from_agent to hl_ceo, "
                "to to hl_cto, mode to handoff, and body to: "
                f"Please answer the user directly with {run_id} and HERMES_PLUGIN_HANDOFF_DONE. "
                "After the tool returns, output the tool result.",
                extra_env={"HERMES_LINK_LOG": str(log_path)},
            )
            events = log_path.read_text(encoding="utf-8")

        self.assertNotIn("[TOOL_ERROR]", completed.stdout)
        self.assertIn(run_id, completed.stdout)
        self.assertIn("HERMES_PLUGIN_HANDOFF_DONE", completed.stdout)
        self.assertIn('"event": "handoff"', events)
        self.assertIn('"from_agent": "hl_ceo"', events)
        self.assertIn('"to_agent": "hl_cto"', events)

    def test_hermes_link_cli_routes_hl_ceo_to_hl_advisor_with_skill_and_org(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "hermes_link.cli",
                "chat",
                "hl_ceo",
                "Send exactly one message to hl_advisor asking it to reply with "
                "HERMES_LINK_SKILL_TEST_PONG. When hl_advisor replies, answer "
                "the user with HERMES_LINK_SKILL_TEST_DONE.",
                "--max-messages",
                "4",
                "--timeout",
                str(TIMEOUT_SECONDS),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS * 4,
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"hermes_link cli failed with exit code {completed.returncode}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )

        self.assertIn("hl_ceo -> hl_advisor:", completed.stdout)
        self.assertIn("hl_advisor -> hl_ceo:", completed.stdout)
        self.assertIn("HERMES_LINK_SKILL_TEST_PONG", completed.stdout)
        self.assertIn("HERMES_LINK_SKILL_TEST_DONE", completed.stdout)

    def test_hermes_link_cli_runs_parallel_conversations(self) -> None:
        run_ids = [f"HERMES_PARALLEL_{uuid.uuid4().hex}" for _ in range(2)]

        def run_conversation(index: int, run_id: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_link.cli",
                    "chat",
                    "hl_ceo",
                    f"This is parallel conversation {index}. Send exactly one message to hl_advisor asking it "
                    f"to reply normally with {run_id} and HERMES_PARALLEL_REPLY_{index}. When hl_advisor "
                    f"replies, answer the user with {run_id} and HERMES_PARALLEL_DONE_{index}.",
                    "--max-messages",
                    "4",
                    "--timeout",
                    str(TIMEOUT_SECONDS),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS * 5,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=len(run_ids)) as executor:
            futures = [
                executor.submit(run_conversation, index, run_id)
                for index, run_id in enumerate(run_ids, start=1)
            ]
            completed_runs = [future.result(timeout=TIMEOUT_SECONDS * 6) for future in futures]

        for index, (run_id, completed) in enumerate(zip(run_ids, completed_runs), start=1):
            if completed.returncode != 0:
                raise AssertionError(
                    f"parallel cli conversation failed with exit code {completed.returncode}\n"
                    f"run_id: {run_id}\n"
                    f"stdout:\n{completed.stdout}\n"
                    f"stderr:\n{completed.stderr}"
                )
            self.assertIn("hl_ceo -> hl_advisor:", completed.stdout)
            self.assertIn("hl_advisor -> hl_ceo:", completed.stdout)
            self.assertIn(run_id, completed.stdout)
            self.assertIn(f"HERMES_PARALLEL_REPLY_{index}", completed.stdout)
            self.assertIn(f"HERMES_PARALLEL_DONE_{index}", completed.stdout)
            for other_run_id in set(run_ids) - {run_id}:
                self.assertNotIn(other_run_id, completed.stdout)

    def test_hermes_link_cli_runs_parallel_employee_sets(self) -> None:
        conversations = [
            {
                "sender": "hl_ceo",
                "recipient": "hl_advisor",
                "reply_marker": "HERMES_PARALLEL_EXEC_REPLY",
                "done_marker": "HERMES_PARALLEL_EXEC_DONE",
                "run_id": f"HERMES_PARALLEL_EXEC_{uuid.uuid4().hex}",
                "thread_id": f"live-exec-{uuid.uuid4().hex[:8]}",
            },
            {
                "sender": "hl_cto",
                "recipient": "hl_backend_engineer",
                "reply_marker": "HERMES_PARALLEL_ENG_REPLY",
                "done_marker": "HERMES_PARALLEL_ENG_DONE",
                "run_id": f"HERMES_PARALLEL_ENG_{uuid.uuid4().hex}",
                "thread_id": f"live-eng-{uuid.uuid4().hex[:8]}",
            },
            {
                "sender": "hl_product_manager",
                "recipient": "hl_frontend_engineer",
                "reply_marker": "HERMES_PARALLEL_PRODUCT_REPLY",
                "done_marker": "HERMES_PARALLEL_PRODUCT_DONE",
                "run_id": f"HERMES_PARALLEL_PRODUCT_{uuid.uuid4().hex}",
                "thread_id": f"live-product-{uuid.uuid4().hex[:8]}",
            },
        ]

        def run_conversation(conversation: dict[str, str], log_path: Path) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_link.cli",
                    "chat",
                    conversation["sender"],
                    f"Send exactly one message to {conversation['recipient']} asking it to reply normally "
                    f"with {conversation['run_id']} and {conversation['reply_marker']}. When "
                    f"{conversation['recipient']} replies, answer the user with {conversation['run_id']} "
                    f"and {conversation['done_marker']}.",
                    "--max-messages",
                    "4",
                    "--timeout",
                    str(TIMEOUT_SECONDS),
                    "--thread-id",
                    conversation["thread_id"],
                    "--log-path",
                    str(log_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS * 5,
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "parallel-events.jsonl"
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(conversations)) as executor:
                futures = [executor.submit(run_conversation, conversation, log_path) for conversation in conversations]
                completed_runs = [future.result(timeout=TIMEOUT_SECONDS * 6) for future in futures]

            _assert_parallel_traces_are_isolated(conversations, log_path)

        all_run_ids = {conversation["run_id"] for conversation in conversations}
        for conversation, completed in zip(conversations, completed_runs):
            if completed.returncode != 0:
                raise AssertionError(
                    f"parallel employee-set cli conversation failed with exit code {completed.returncode}\n"
                    f"sender: {conversation['sender']}\n"
                    f"recipient: {conversation['recipient']}\n"
                    f"stdout:\n{completed.stdout}\n"
                    f"stderr:\n{completed.stderr}"
                )
            self.assertIn(f"{conversation['sender']} -> {conversation['recipient']}:", completed.stdout)
            self.assertIn(f"{conversation['recipient']} -> {conversation['sender']}:", completed.stdout)
            self.assertIn(conversation["run_id"], completed.stdout)
            self.assertIn(conversation["reply_marker"], completed.stdout)
            self.assertIn(conversation["done_marker"], completed.stdout)
            for other_run_id in all_run_ids - {conversation["run_id"]}:
                self.assertNotIn(other_run_id, completed.stdout)

    def test_hermes_link_cli_send_all_scatter_gathers_direct_reports(self) -> None:
        run_id = f"HERMES_SEND_ALL_{uuid.uuid4().hex}"
        thread_id = f"live-send-all-{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "send-all-events.jsonl"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_link.cli",
                    "chat",
                    "hl_cto",
                    "Output exactly one SEND_ALL block and no extra text. Use this exact block:\n"
                    "SEND_ALL:\n"
                    f"- hl_backend_engineer: Reply normally with {run_id} and HERMES_SEND_ALL_BACKEND.\n"
                    f"- hl_frontend_engineer: Reply normally with {run_id} and HERMES_SEND_ALL_FRONTEND.\n"
                    "After both replies are gathered, answer the user with "
                    f"{run_id}, HERMES_SEND_ALL_BACKEND, HERMES_SEND_ALL_FRONTEND, and HERMES_SEND_ALL_DONE.",
                    "--max-messages",
                    "4",
                    "--timeout",
                    str(TIMEOUT_SECONDS),
                    "--thread-id",
                    thread_id,
                    "--log-path",
                    str(log_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS * 5,
            )
            if completed.returncode != 0:
                raise AssertionError(
                    f"SEND_ALL cli route failed with exit code {completed.returncode}\n"
                    f"stdout:\n{completed.stdout}\n"
                    f"stderr:\n{completed.stderr}"
                )
            trace = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_link.cli",
                    "trace",
                    thread_id,
                    "--path",
                    str(log_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )

        self.assertIn("thread_id: " + thread_id, completed.stdout)
        self.assertIn("hl_cto -> hl_backend_engineer:", completed.stdout)
        self.assertIn("hl_cto -> hl_frontend_engineer:", completed.stdout)
        self.assertIn("HERMES_SEND_ALL_DONE", completed.stdout)
        self.assertIn("HERMES_SEND_ALL_BACKEND", completed.stdout)
        self.assertIn("HERMES_SEND_ALL_FRONTEND", completed.stdout)
        self.assertEqual(trace.returncode, 0, trace.stderr)
        self.assertIn("scatter hl_cto -> [hl_backend_engineer, hl_frontend_engineer]", trace.stdout)
        self.assertIn("gather hl_backend_engineer", trace.stdout)
        self.assertIn("gather hl_frontend_engineer", trace.stdout)

    def test_hermes_link_cli_send_all_scatter_gathers_group(self) -> None:
        run_id = f"HERMES_GROUP_SEND_ALL_{uuid.uuid4().hex}"
        thread_id = f"live-group-send-all-{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "group-send-all-events.jsonl"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_link.cli",
                    "chat",
                    "hl_cto",
                    "Output exactly one SEND_ALL directive and no extra text. Use this exact directive:\n"
                    f"SEND_ALL @engineering: Reply normally with {run_id} and your role marker. "
                    "Backend must include HERMES_GROUP_BACKEND. Frontend must include HERMES_GROUP_FRONTEND.\n"
                    "After both replies are gathered, answer the user with "
                    f"{run_id}, HERMES_GROUP_BACKEND, HERMES_GROUP_FRONTEND, and HERMES_GROUP_DONE.",
                    "--max-messages",
                    "4",
                    "--timeout",
                    str(TIMEOUT_SECONDS),
                    "--thread-id",
                    thread_id,
                    "--log-path",
                    str(log_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS * 5,
            )
            if completed.returncode != 0:
                raise AssertionError(
                    f"group SEND_ALL cli route failed with exit code {completed.returncode}\n"
                    f"stdout:\n{completed.stdout}\n"
                    f"stderr:\n{completed.stderr}"
                )
            trace = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_link.cli",
                    "trace",
                    thread_id,
                    "--path",
                    str(log_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )

        self.assertIn("thread_id: " + thread_id, completed.stdout)
        self.assertIn("hl_cto -> hl_backend_engineer:", completed.stdout)
        self.assertIn("hl_cto -> hl_frontend_engineer:", completed.stdout)
        self.assertIn("HERMES_GROUP_DONE", completed.stdout)
        self.assertIn("HERMES_GROUP_BACKEND", completed.stdout)
        self.assertIn("HERMES_GROUP_FRONTEND", completed.stdout)
        self.assertEqual(trace.returncode, 0, trace.stderr)
        self.assertIn("scatter hl_cto -> [hl_backend_engineer, hl_frontend_engineer]", trace.stdout)
        self.assertIn("gather hl_backend_engineer", trace.stdout)
        self.assertIn("gather hl_frontend_engineer", trace.stdout)

    def test_hermes_link_cli_send_all_scatter_gathers_direct_reports_builtin(self) -> None:
        run_id = f"HERMES_DIRECT_REPORTS_{uuid.uuid4().hex}"
        thread_id = f"live-direct-reports-{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "direct-reports-events.jsonl"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_link.cli",
                    "chat",
                    "hl_cto",
                    "Output exactly one SEND_ALL directive and no extra text. Use this exact directive:\n"
                    f"SEND_ALL @direct_reports: Reply normally with {run_id} and your role marker. "
                    "Backend must include HERMES_DIRECT_BACKEND. Frontend must include HERMES_DIRECT_FRONTEND.\n"
                    "After both replies are gathered, answer the user with "
                    f"{run_id}, HERMES_DIRECT_BACKEND, HERMES_DIRECT_FRONTEND, and HERMES_DIRECT_DONE.",
                    "--max-messages",
                    "4",
                    "--timeout",
                    str(TIMEOUT_SECONDS),
                    "--thread-id",
                    thread_id,
                    "--log-path",
                    str(log_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS * 5,
            )
            if completed.returncode != 0:
                raise AssertionError(
                    f"@direct_reports SEND_ALL cli route failed with exit code {completed.returncode}\n"
                    f"stdout:\n{completed.stdout}\n"
                    f"stderr:\n{completed.stderr}"
                )
            trace = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_link.cli",
                    "trace",
                    thread_id,
                    "--path",
                    str(log_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )

        self.assertIn("thread_id: " + thread_id, completed.stdout)
        self.assertIn("hl_cto -> hl_backend_engineer:", completed.stdout)
        self.assertIn("hl_cto -> hl_frontend_engineer:", completed.stdout)
        self.assertIn("HERMES_DIRECT_DONE", completed.stdout)
        self.assertIn("HERMES_DIRECT_BACKEND", completed.stdout)
        self.assertIn("HERMES_DIRECT_FRONTEND", completed.stdout)
        self.assertEqual(trace.returncode, 0, trace.stderr)
        self.assertIn("scatter hl_cto -> [hl_backend_engineer, hl_frontend_engineer]", trace.stdout)
        self.assertIn("gather hl_backend_engineer", trace.stdout)
        self.assertIn("gather hl_frontend_engineer", trace.stdout)

    def test_hermes_link_cli_handoffs_to_target_agent(self) -> None:
        run_id = f"HERMES_HANDOFF_{uuid.uuid4().hex}"
        thread_id = f"live-handoff-{uuid.uuid4().hex[:8]}"
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "handoff-events.jsonl"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_link.cli",
                    "chat",
                    "hl_ceo",
                    "Output exactly one HANDOFF directive and no extra text. Use this exact directive:\n"
                    f"HANDOFF hl_cto: Please answer the user directly with {run_id} and HERMES_HANDOFF_CTO_DONE.",
                    "--max-messages",
                    "4",
                    "--timeout",
                    str(TIMEOUT_SECONDS),
                    "--thread-id",
                    thread_id,
                    "--log-path",
                    str(log_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS * 4,
            )
            if completed.returncode != 0:
                raise AssertionError(
                    f"handoff cli route failed with exit code {completed.returncode}\n"
                    f"stdout:\n{completed.stdout}\n"
                    f"stderr:\n{completed.stderr}"
                )
            trace = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_link.cli",
                    "trace",
                    thread_id,
                    "--path",
                    str(log_path),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )

        self.assertIn("thread_id: " + thread_id, completed.stdout)
        self.assertIn("hl_ceo -> hl_cto:", completed.stdout)
        self.assertIn(run_id, completed.stdout)
        self.assertIn("HERMES_HANDOFF_CTO_DONE", completed.stdout)
        self.assertEqual(trace.returncode, 0, trace.stderr)
        self.assertIn("handoff hl_ceo", trace.stdout)
        self.assertIn("-> hl_cto", trace.stdout)
        self.assertIn("hl_cto final", trace.stdout)

    def test_hermes_link_cli_notifies_sender_when_policy_blocks_route(self) -> None:
        run_id = f"HERMES_POLICY_BLOCK_{uuid.uuid4().hex}"
        with tempfile.TemporaryDirectory() as tmpdir:
            org = _write_policy_block_org(Path(tmpdir))
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "hermes_link.cli",
                    "chat",
                    "hl_advisor",
                    "Your entire response must be exactly this one Hermes Link SEND directive and no extra text. "
                    "Do not route through another agent. Do not use HANDOFF. Do not use SEND_ALL. "
                    f"Output exactly: SEND hl_backend_engineer: {run_id}",
                    "--org",
                    str(org),
                    "--max-messages",
                    "6",
                    "--timeout",
                    str(TIMEOUT_SECONDS),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS * 3,
            )

        if completed.returncode != 0:
            raise AssertionError(
                f"policy block cli route failed with exit code {completed.returncode}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )

        self.assertIn("routing policy blocked", completed.stdout)
        self.assertIn("hl_advisor is not allowed to send messages to hl_backend_engineer", completed.stdout)

    def test_hermes_link_cli_allows_strict_hierarchy_routes(self) -> None:
        route_pairs = [
            ("hl_ceo", "hl_cto"),
            ("hl_cto", "hl_backend_engineer"),
            ("hl_backend_engineer", "hl_frontend_engineer"),
            ("hl_backend_engineer", "hl_ceo"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            org = _write_strict_org(Path(tmpdir))
            for sender, recipient in route_pairs:
                with self.subTest(sender=sender, recipient=recipient):
                    run_id = f"HERMES_STRICT_ALLOWED_{uuid.uuid4().hex}"
                    completed = subprocess.run(
                        [
                            sys.executable,
                            "-m",
                            "hermes_link.cli",
                            "chat",
                            sender,
                            "Output exactly one Hermes Link SEND directive and no extra text: "
                            f"SEND {recipient}: Please answer normally with {run_id}.",
                            "--org",
                            str(org),
                            "--max-messages",
                            "6",
                            "--timeout",
                            str(TIMEOUT_SECONDS),
                        ],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=TIMEOUT_SECONDS * 7,
                    )
                    if completed.returncode != 0:
                        raise AssertionError(
                            f"allowed strict route failed with exit code {completed.returncode}\n"
                            f"route: {sender} -> {recipient}\n"
                            f"stdout:\n{completed.stdout}\n"
                            f"stderr:\n{completed.stderr}"
                        )
                    self.assertNotIn("routing policy blocked", completed.stdout)
                    self.assertIn(f"{sender} -> {recipient}:", completed.stdout)
                    self.assertIn(run_id, completed.stdout)

    def test_hl_ceo_advisor_ceo_roundtrip(self) -> None:
        self.assertIsNotNone(shutil.which("hl_ceo"), "hl_ceo alias is not on PATH")
        self.assertIsNotNone(shutil.which("hl_advisor"), "hl_advisor alias is not on PATH")

        runner = _runner()
        first = runner.request_send(
            "hl_ceo",
            "Use the Hermes Link SEND directive. Send exactly one message to "
            "hl_advisor. The message body must include HERMES_MEDIATED_PING and "
            "ask hl_advisor to reply to hl_ceo with HERMES_MEDIATED_PONG.",
        )
        second = runner.request_send(
            "hl_advisor",
            "You received this routed message from hl_ceo:\n\n"
            f"{first.message.body}\n\n"
            "Use the Hermes Link SEND directive. Send exactly one response "
            "message to hl_ceo. The message body must include "
            "HERMES_MEDIATED_PONG.",
        )
        hl_ceo_sessions = [first.turn.session_id]
        hl_advisor_sessions = [second.turn.session_id]

        self.assertEqual(
            [(message.sender, message.recipient) for message in [first.message, second.message]],
            [("hl_ceo", "hl_advisor"), ("hl_advisor", "hl_ceo")],
        )
        self.assertIn("HERMES_MEDIATED_PING", first.message.body)
        self.assertIn("HERMES_MEDIATED_PONG", second.message.body)
        self.assertEqual(hl_ceo_sessions, [hl_ceo_sessions[0]])
        self.assertEqual(hl_advisor_sessions, [hl_advisor_sessions[0]])

    def test_hl_ceo_and_advisor_converse_for_six_messages_on_same_sessions(self) -> None:
        self.assertIsNotNone(shutil.which("hl_ceo"), "hl_ceo alias is not on PATH")
        self.assertIsNotNone(shutil.which("hl_advisor"), "hl_advisor alias is not on PATH")

        run_id = f"HERMES_SIX_RUN_{uuid.uuid4().hex}"
        runner = _runner()
        routed = []
        turns = []
        previous_message = "No previous message."
        steps = [
            ("hl_ceo", "hl_advisor", 1),
            ("hl_advisor", "hl_ceo", 2),
            ("hl_ceo", "hl_advisor", 3),
            ("hl_advisor", "hl_ceo", 4),
            ("hl_ceo", "hl_advisor", 5),
            ("hl_advisor", "hl_ceo", 6),
        ]

        for sender, recipient, number in steps:
            routed_send = runner.request_send(
                sender,
                f"Run id: {run_id}. You are creating a six-message Hermes "
                "Link smoke test using the SEND directive. You received this "
                f"previous message: {previous_message}\n\n"
                f"Now send message {number} to {recipient}. Output exactly "
                f"one SEND directive to {recipient}. The message body must "
                f"include HERMES_SIX_MSG_{number}.",
            )
            routed.append(routed_send.message)
            turns.append(routed_send.turn)
            previous_message = routed_send.message.body

        self.assertEqual(len(routed), 6)
        self.assertEqual(
            [(message.sender, message.recipient) for message in routed],
            [
                ("hl_ceo", "hl_advisor"),
                ("hl_advisor", "hl_ceo"),
                ("hl_ceo", "hl_advisor"),
                ("hl_advisor", "hl_ceo"),
                ("hl_ceo", "hl_advisor"),
                ("hl_advisor", "hl_ceo"),
            ],
        )
        for index, message in enumerate(routed, start=1):
            self.assertIn(f"HERMES_SIX_MSG_{index}", message.body)

        hl_ceo_sessions = _session_ids_for(turns, "hl_ceo")
        hl_advisor_sessions = _session_ids_for(turns, "hl_advisor")
        self.assertEqual(len(hl_ceo_sessions), 3)
        self.assertEqual(len(hl_advisor_sessions), 3)
        self.assertEqual(set(hl_ceo_sessions), {hl_ceo_sessions[0]})
        self.assertEqual(set(hl_advisor_sessions), {hl_advisor_sessions[0]})
        self.assertNotEqual(hl_ceo_sessions[0], hl_advisor_sessions[0])

        expected_markers = {
            "hl_ceo": ["HERMES_SIX_MSG_1", "HERMES_SIX_MSG_3", "HERMES_SIX_MSG_5"],
            "hl_advisor": ["HERMES_SIX_MSG_2", "HERMES_SIX_MSG_4", "HERMES_SIX_MSG_6"],
        }
        self.assertEqual(
            _markers_for_turns(turns, "hl_ceo", expected_markers["hl_ceo"]),
            expected_markers["hl_ceo"],
        )
        self.assertEqual(
            _markers_for_turns(turns, "hl_advisor", expected_markers["hl_advisor"]),
            expected_markers["hl_advisor"],
        )
        self.assertGreaterEqual(_assistant_message_count("hl_ceo", hl_ceo_sessions[0]), 3)
        self.assertGreaterEqual(_assistant_message_count("hl_advisor", hl_advisor_sessions[0]), 3)


def _runner() -> HermesRunner:
    return HermesRunner(load_org(REPO_ROOT / "config" / "org.yaml"), cwd=REPO_ROOT, timeout=TIMEOUT_SECONDS)


def _run_hl_ceo_with_plugin(prompt: str, *, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [
            "hl_ceo",
            "chat",
            "-Q",
            "--toolsets",
            "hermes-link",
            "-q",
            prompt,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS * 3,
        env={**os.environ, **(extra_env or {})},
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"hl_ceo plugin route failed with exit code {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def _assert_parallel_traces_are_isolated(conversations: list[dict[str, str]], log_path: Path) -> None:
    all_run_ids = {conversation["run_id"] for conversation in conversations}
    for conversation in conversations:
        trace = subprocess.run(
            [
                sys.executable,
                "-m",
                "hermes_link.cli",
                "trace",
                conversation["thread_id"],
                "--path",
                str(log_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        if trace.returncode != 0:
            raise AssertionError(
                f"trace command failed with exit code {trace.returncode}\n"
                f"stdout:\n{trace.stdout}\n"
                f"stderr:\n{trace.stderr}"
            )
        sessions = subprocess.run(
            [
                sys.executable,
                "-m",
                "hermes_link.cli",
                "sessions",
                "--thread",
                conversation["thread_id"],
                "--log-path",
                str(log_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        if sessions.returncode != 0:
            raise AssertionError(
                f"sessions command failed with exit code {sessions.returncode}\n"
                f"stdout:\n{sessions.stdout}\n"
                f"stderr:\n{sessions.stderr}"
            )
        if conversation["run_id"] not in trace.stdout:
            raise AssertionError(f"trace did not include run id {conversation['run_id']}:\n{trace.stdout}")
        for label, output in (("trace", trace.stdout), ("sessions", sessions.stdout)):
            if conversation["sender"] not in output:
                raise AssertionError(f"{label} did not include sender {conversation['sender']}:\n{output}")
            if conversation["recipient"] not in output:
                raise AssertionError(f"{label} did not include recipient {conversation['recipient']}:\n{output}")
            for other_run_id in all_run_ids - {conversation["run_id"]}:
                if other_run_id in output:
                    raise AssertionError(f"{label} leaked run id {other_run_id} into {conversation['thread_id']}:\n{output}")


def _write_policy_block_org(root: Path) -> Path:
    return _write_strict_org(root)


def _write_strict_org(root: Path) -> Path:
    skill = root / "skills" / "agent-comms" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("Use SEND agent_id: message.", encoding="utf-8")
    org = root / "config" / "org.yaml"
    org.parent.mkdir()
    org.write_text(
        "\n".join(
            [
                "agents:",
                "  hl_ceo:",
                "    command: hl_ceo",
                "    expertise: Executive sender",
                "  hl_advisor:",
                "    command: hl_advisor",
                "    expertise: Advisor recipient",
                "    manager: hl_ceo",
                "  hl_cto:",
                "    command: hl_cto",
                "    expertise: Technical executive",
                "    manager: hl_ceo",
                "  hl_backend_engineer:",
                "    command: hl_backend_engineer",
                "    expertise: Backend specialist",
                "    manager: hl_cto",
                "  hl_frontend_engineer:",
                "    command: hl_frontend_engineer",
                "    expertise: Frontend specialist",
                "    manager: hl_cto",
                "routing: strict_hierarchical",
                "skill: skills/agent-comms/SKILL.md",
            ]
        ),
        encoding="utf-8",
    )
    return org


def _session_ids_for(turns: object, agent: str) -> list[str]:
    return [turn.session_id for turn in turns if turn.agent == agent]


def _markers_for_turns(turns: object, agent: str, expected: list[str]) -> list[str]:
    markers = []
    for turn in turns:
        if turn.agent != agent:
            continue
        markers.extend(marker for marker in expected if marker in turn.response)
    return markers


def _assistant_messages_for_session(command: str, session_id: str, run_id: str) -> list[str]:
    contents = _assistant_message_contents(command, session_id)
    messages_for_run = [content for content in contents if run_id in content or "HERMES_SIX_MSG_" in content]
    return [
        marker
        for content in messages_for_run
        for marker in re.findall(r"HERMES_SIX_MSG_\d", content)
    ]


def _assistant_message_count(command: str, session_id: str) -> int:
    return len(_assistant_message_contents(command, session_id))


def _assistant_message_contents(command: str, session_id: str) -> list[str]:
    completed = subprocess.run(
        [command, "sessions", "export", "--session-id", session_id, "-"],
        check=False,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"{command} sessions export failed with exit code {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    exported = json.loads(completed.stdout)
    return [
        str(message.get("content", ""))
        for message in exported["messages"]
        if message.get("role") == "assistant"
    ]


def _recent_sessions_contain(command: str, *needles: str) -> bool:
    for session_id in _recent_session_ids(command):
        completed = subprocess.run(
            [command, "sessions", "export", "--session-id", session_id, "-"],
            check=False,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            continue
        if all(needle in completed.stdout for needle in needles):
            return True
    return False


def _recent_session_ids(command: str, limit: int = 8) -> list[str]:
    completed = subprocess.run(
        [command, "sessions", "list"],
        check=False,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"{command} sessions list failed with exit code {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return re.findall(r"\b\d{8}_\d{6}_[0-9a-f]+\b", completed.stdout)[:limit]


if __name__ == "__main__":
    unittest.main()
