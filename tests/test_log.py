import tempfile
import unittest
from pathlib import Path

from hermes_link.log import EventLog, format_event, iter_events


class LogTests(unittest.TestCase):
    def test_event_log_writes_jsonl_and_formats_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            log = EventLog(path)

            log.write("message", from_agent="agent_a", to_agent="agent_b", body="hello")

            events = list(iter_events(path))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "message")
        self.assertEqual(format_event(events[0]), "agent_a -> agent_b: hello")


if __name__ == "__main__":
    unittest.main()
