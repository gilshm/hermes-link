import unittest

from hermes_link import Agent, Message, Runtime
from hermes_link.demo import run_demo


class RoundTripTests(unittest.TestCase):
    def test_agent_a_sends_to_agent_b_and_agent_b_replies(self) -> None:
        received_by_a: list[Message] = []

        def agent_a(message: Message) -> None:
            received_by_a.append(message)
            return None

        def agent_b(message: Message) -> Message:
            self.assertEqual(message, Message("agent_a", "agent_b", "ping"))
            return Message("agent_b", "agent_a", "pong")

        runtime = Runtime()
        runtime.register(Agent("agent_a", agent_a))
        runtime.register(Agent("agent_b", agent_b))

        transcript = runtime.send(Message("agent_a", "agent_b", "ping"))

        self.assertEqual(
            transcript,
            [
                Message("agent_a", "agent_b", "ping"),
                Message("agent_b", "agent_a", "pong"),
            ],
        )
        self.assertEqual(received_by_a, [Message("agent_b", "agent_a", "pong")])

    def test_demo_roundtrip(self) -> None:
        self.assertEqual(
            run_demo(),
            [
                Message("agent_a", "agent_b", "ping"),
                Message("agent_b", "agent_a", "pong"),
            ],
        )

    def test_unknown_agent_is_rejected(self) -> None:
        runtime = Runtime()
        runtime.register(Agent("agent_a", lambda message: None))

        with self.assertRaisesRegex(ValueError, "unknown agent: agent_b"):
            runtime.send(Message("agent_a", "agent_b", "ping"))


if __name__ == "__main__":
    unittest.main()
