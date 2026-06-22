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
                    "Output exactly one Hermes Link SEND directive and no extra text: "
                    f"SEND hl_backend_engineer: {run_id}",
                    "--org",
                    str(org),
                    "--max-messages",
                    "2",
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


def _run_hl_ceo_with_plugin(prompt: str) -> subprocess.CompletedProcess[str]:
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
    )
    if completed.returncode != 0:
        raise AssertionError(
            f"hl_ceo plugin route failed with exit code {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


def _write_policy_block_org(root: Path) -> Path:
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
