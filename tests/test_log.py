import tempfile
import unittest
from pathlib import Path

from hermes_link.log import EventLog, format_event, format_trace, iter_events, trace_events


class LogTests(unittest.TestCase):
    def test_event_log_writes_jsonl_and_formats_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            log = EventLog(path)

            log.write(
                "message",
                thread_id="thread-123456789",
                from_agent="agent_a",
                to_agent="agent_b",
                body="hello",
            )

            events = list(iter_events(path))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "message")
        formatted = format_event(events[0])
        self.assertIn("[ad-123456789]", formatted)
        self.assertIn("├─ agent_a -> agent_b: hello", formatted)

    def test_format_event_can_colorize(self) -> None:
        formatted = format_event(
            {
                "event": "message",
                "ts": 1,
                "thread_id": "thread",
                "from_agent": "agent_a",
                "to_agent": "agent_b",
                "body": "hello",
            },
            color=True,
        )

        self.assertIn("\033[", formatted)

    def test_trace_events_filters_and_formats_thread(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            log = EventLog(path)
            log.write("bridge_request", thread_id="thread-a", from_agent="agent_a", to_agent="agent_b", body="start")
            log.write(
                "message",
                thread_id="thread-a",
                from_agent="agent_b",
                to_agent="agent_a",
                from_session_id="session-b-12345678",
                to_session_id="session-a-87654321",
                body="reply",
            )
            log.write("final", thread_id="thread-b", agent="agent_a", body="ignore")

            events = trace_events(path, "thread-a")
            formatted = format_trace(events, thread_id="thread-a")

        self.assertEqual(len(events), 2)
        self.assertIn("Trace thread-a", formatted)
        self.assertIn("bridge agent_a -> agent_b: start", formatted)
        self.assertIn("agent_b(12345678) -> agent_a(87654321): reply", formatted)


if __name__ == "__main__":
    unittest.main()
