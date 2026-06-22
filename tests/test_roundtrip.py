import unittest

from hermes_link import Agent, Message, Runtime
from hermes_link.demo import run_demo


class RoundTripTests(unittest.TestCase):
    def test_hl_ceo_sends_to_advisor_and_advisor_replies(self) -> None:
        received_by_hl_ceo: list[Message] = []

        def hl_ceo(message: Message) -> None:
            received_by_hl_ceo.append(message)
            return None

        def hl_advisor(message: Message) -> Message:
            self.assertEqual(message, Message("hl_ceo", "hl_advisor", "ping"))
            return Message("hl_advisor", "hl_ceo", "pong")

        runtime = Runtime()
        runtime.register(Agent("hl_ceo", hl_ceo))
        runtime.register(Agent("hl_advisor", hl_advisor))

        transcript = runtime.send(Message("hl_ceo", "hl_advisor", "ping"))

        self.assertEqual(
            transcript,
            [
                Message("hl_ceo", "hl_advisor", "ping"),
                Message("hl_advisor", "hl_ceo", "pong"),
            ],
        )
        self.assertEqual(received_by_hl_ceo, [Message("hl_advisor", "hl_ceo", "pong")])

    def test_demo_roundtrip(self) -> None:
        self.assertEqual(
            run_demo(),
            [
                Message("hl_ceo", "hl_advisor", "ping"),
                Message("hl_advisor", "hl_ceo", "pong"),
            ],
        )

    def test_unknown_agent_is_rejected(self) -> None:
        runtime = Runtime()
        runtime.register(Agent("hl_ceo", lambda message: None))

        with self.assertRaisesRegex(ValueError, "unknown agent: hl_advisor"):
            runtime.send(Message("hl_ceo", "hl_advisor", "ping"))


if __name__ == "__main__":
    unittest.main()
