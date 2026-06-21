import json
import os
import re
import shutil
import subprocess
import sys
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
    def test_user_to_agent_a_routes_single_message_to_agent_b_through_plugin(self) -> None:
        run_id = f"HERMES_USER_PLUGIN_SINGLE_{uuid.uuid4().hex}"
        completed = _run_agent_a_with_plugin(
            "Use the route_message tool exactly once. Set from_agent to agent_a, "
            "to to agent_b, and body to: "
            f"{run_id} HERMES_USER_PLUGIN_SINGLE_MSG_1. "
            "After the tool returns, answer with HERMES_USER_PLUGIN_SINGLE_DONE."
        )

        self.assertNotIn("[TOOL_ERROR]", completed.stdout)
        self.assertIn("HERMES_USER_PLUGIN_SINGLE_DONE", completed.stdout)
        self.assertTrue(_recent_sessions_contain("agent_b", run_id, "HERMES_USER_PLUGIN_SINGLE_MSG_1"))

    def test_user_to_agent_a_routes_six_messages_through_plugin(self) -> None:
        run_id = f"HERMES_USER_PLUGIN_SIX_{uuid.uuid4().hex}"
        completed = _run_agent_a_with_plugin(
            "Use the route_message tool exactly once. Set from_agent to agent_a, "
            "to to agent_b, and max_messages to 8. The body must ask agent_b "
            "to conduct a six-message Hermes Link exchange using SEND directives. "
            "Count this tool-delivered body as message 1 from agent_a to agent_b, "
            f"and include {run_id} and HERMES_USER_PLUGIN_SIX_MSG_1 in that body. Then agent_b "
            "must SEND message 2 to agent_a with HERMES_USER_PLUGIN_SIX_MSG_2, "
            "agent_a must SEND message 3 to agent_b with HERMES_USER_PLUGIN_SIX_MSG_3, "
            "agent_b must SEND message 4 to agent_a with HERMES_USER_PLUGIN_SIX_MSG_4, "
            "agent_a must SEND message 5 to agent_b with HERMES_USER_PLUGIN_SIX_MSG_5, "
            "and agent_b must SEND message 6 to agent_a with HERMES_USER_PLUGIN_SIX_MSG_6. "
            "After the tool returns, answer with HERMES_USER_PLUGIN_SIX_DONE."
        )

        self.assertNotIn("[TOOL_ERROR]", completed.stdout)
        self.assertIn("HERMES_USER_PLUGIN_SIX_DONE", completed.stdout)
        self.assertTrue(_recent_sessions_contain("agent_b", run_id, "HERMES_USER_PLUGIN_SIX_MSG_1"))
        for index in (2, 4, 6):
            self.assertTrue(_recent_sessions_contain("agent_b", run_id, f"HERMES_USER_PLUGIN_SIX_MSG_{index}"))
        for index in (3, 5):
            self.assertTrue(_recent_sessions_contain("agent_a", run_id, f"HERMES_USER_PLUGIN_SIX_MSG_{index}"))

    def test_agent_a_can_route_to_agent_b_through_plugin_tool(self) -> None:
        completed = _run_agent_a_with_plugin(
            "Use the route_message tool to send agent_b this exact message: "
            "HERMES_PLUGIN_TEST_PING. Then output the tool result."
        )

        self.assertTrue(completed.stdout.strip())
        self.assertNotIn("[TOOL_ERROR]", completed.stdout)

    def test_hermes_link_cli_routes_agent_a_to_agent_b_with_skill_and_org(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "hermes_link.cli",
                "chat",
                "agent_a",
                "Send exactly one message to agent_b asking it to reply with "
                "HERMES_LINK_SKILL_TEST_PONG. When agent_b replies, answer "
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

        self.assertIn("agent_a -> agent_b:", completed.stdout)
        self.assertIn("agent_b -> agent_a:", completed.stdout)
        self.assertIn("HERMES_LINK_SKILL_TEST_PONG", completed.stdout)
        self.assertIn("HERMES_LINK_SKILL_TEST_DONE", completed.stdout)

    def test_agent_a_agent_b_agent_a_roundtrip(self) -> None:
        self.assertIsNotNone(shutil.which("agent_a"), "agent_a alias is not on PATH")
        self.assertIsNotNone(shutil.which("agent_b"), "agent_b alias is not on PATH")

        runner = _runner()
        first = runner.request_send(
            "agent_a",
            "Use the Hermes Link SEND directive. Send exactly one message to "
            "agent_b. The message body must include HERMES_MEDIATED_PING and "
            "ask agent_b to reply to agent_a with HERMES_MEDIATED_PONG.",
        )
        second = runner.request_send(
            "agent_b",
            "You received this routed message from agent_a:\n\n"
            f"{first.message.body}\n\n"
            "Use the Hermes Link SEND directive. Send exactly one response "
            "message to agent_a. The message body must include "
            "HERMES_MEDIATED_PONG.",
        )
        agent_a_sessions = [first.turn.session_id]
        agent_b_sessions = [second.turn.session_id]

        self.assertEqual(
            [(message.sender, message.recipient) for message in [first.message, second.message]],
            [("agent_a", "agent_b"), ("agent_b", "agent_a")],
        )
        self.assertIn("HERMES_MEDIATED_PING", first.message.body)
        self.assertIn("HERMES_MEDIATED_PONG", second.message.body)
        self.assertEqual(agent_a_sessions, [agent_a_sessions[0]])
        self.assertEqual(agent_b_sessions, [agent_b_sessions[0]])

    def test_agent_a_and_agent_b_converse_for_six_messages_on_same_sessions(self) -> None:
        self.assertIsNotNone(shutil.which("agent_a"), "agent_a alias is not on PATH")
        self.assertIsNotNone(shutil.which("agent_b"), "agent_b alias is not on PATH")

        run_id = f"HERMES_SIX_RUN_{uuid.uuid4().hex}"
        runner = _runner()
        routed = []
        turns = []
        previous_message = "No previous message."
        steps = [
            ("agent_a", "agent_b", 1),
            ("agent_b", "agent_a", 2),
            ("agent_a", "agent_b", 3),
            ("agent_b", "agent_a", 4),
            ("agent_a", "agent_b", 5),
            ("agent_b", "agent_a", 6),
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
                ("agent_a", "agent_b"),
                ("agent_b", "agent_a"),
                ("agent_a", "agent_b"),
                ("agent_b", "agent_a"),
                ("agent_a", "agent_b"),
                ("agent_b", "agent_a"),
            ],
        )
        for index, message in enumerate(routed, start=1):
            self.assertIn(f"HERMES_SIX_MSG_{index}", message.body)

        agent_a_sessions = _session_ids_for(turns, "agent_a")
        agent_b_sessions = _session_ids_for(turns, "agent_b")
        self.assertEqual(len(agent_a_sessions), 3)
        self.assertEqual(len(agent_b_sessions), 3)
        self.assertEqual(set(agent_a_sessions), {agent_a_sessions[0]})
        self.assertEqual(set(agent_b_sessions), {agent_b_sessions[0]})
        self.assertNotEqual(agent_a_sessions[0], agent_b_sessions[0])

        expected_markers = {
            "agent_a": ["HERMES_SIX_MSG_1", "HERMES_SIX_MSG_3", "HERMES_SIX_MSG_5"],
            "agent_b": ["HERMES_SIX_MSG_2", "HERMES_SIX_MSG_4", "HERMES_SIX_MSG_6"],
        }
        self.assertEqual(
            _markers_for_turns(turns, "agent_a", expected_markers["agent_a"]),
            expected_markers["agent_a"],
        )
        self.assertEqual(
            _markers_for_turns(turns, "agent_b", expected_markers["agent_b"]),
            expected_markers["agent_b"],
        )
        self.assertGreaterEqual(_assistant_message_count("agent_a", agent_a_sessions[0]), 3)
        self.assertGreaterEqual(_assistant_message_count("agent_b", agent_b_sessions[0]), 3)


def _runner() -> HermesRunner:
    return HermesRunner(load_org(REPO_ROOT / "config" / "org.yaml"), cwd=REPO_ROOT, timeout=TIMEOUT_SECONDS)


def _run_agent_a_with_plugin(prompt: str) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [
            "agent_a",
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
            f"agent_a plugin route failed with exit code {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return completed


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
