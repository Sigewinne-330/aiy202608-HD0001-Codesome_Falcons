import sys
import unittest
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.managebac_ical import (  # noqa: E402
    ManageBacCalendarParseError,
    parse_managebac_calendar,
)


FIXTURE = Path(__file__).parent / "fixtures" / "managebac_calendar.ics"


class ManageBacICalendarTests(unittest.TestCase):
    def test_parses_tasks_deadlines_and_skips_plain_events(self):
        result = parse_managebac_calendar(FIXTURE.read_bytes(), timezone_name="Asia/Shanghai")
        self.assertEqual("Student Calendar", result.calendar_name)
        self.assertEqual(3, result.total_items)
        self.assertEqual(2, len(result.items))
        self.assertEqual(1, result.skipped_items)

        physics = next(item for item in result.items if item.subject == "Physics")
        self.assertEqual("task", physics.kind)
        self.assertEqual(datetime(2026, 9, 10, 23, 59), physics.deadline)
        self.assertEqual("Task: Submit the first draft on ManageBac.", physics.description)
        self.assertNotIn("<p>", physics.description)

        economics = next(item for item in result.items if item.subject == "Economics")
        self.assertEqual("deadline", economics.kind)
        self.assertEqual(datetime(2026, 9, 12, 16, 0), economics.deadline)

    def test_duplicate_uid_uses_newest_sequence(self):
        content = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:same-task\r
DTSTART;VALUE=DATE:20260910\r
SUMMARY:Old Assignment\r
CATEGORIES:Task\r
SEQUENCE:1\r
END:VEVENT\r
BEGIN:VEVENT\r
UID:same-task\r
DTSTART;VALUE=DATE:20260912\r
SUMMARY:Updated Assignment\r
CATEGORIES:Task\r
SEQUENCE:2\r
END:VEVENT\r
END:VCALENDAR\r
"""
        result = parse_managebac_calendar(content)
        self.assertEqual(1, len(result.items))
        self.assertEqual("Updated Assignment", result.items[0].title)
        self.assertEqual(datetime(2026, 9, 12, 23, 59), result.items[0].deadline)

    def test_vtodo_due_and_cancelled_event(self):
        content = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VTODO\r
UID:todo-1\r
DUE:20260915T100000Z\r
SUMMARY:Read chapter\r
STATUS:CANCELLED\r
END:VTODO\r
END:VCALENDAR\r
"""
        item = parse_managebac_calendar(content, timezone_name="Asia/Shanghai").items[0]
        self.assertEqual("task", item.kind)
        self.assertEqual("cancelled", item.status)
        self.assertEqual(datetime(2026, 9, 15, 18, 0), item.deadline)

    def test_rejects_invalid_or_empty_calendar(self):
        for content in (b"", b"not a calendar"):
            with self.subTest(content=content):
                with self.assertRaises(ManageBacCalendarParseError):
                    parse_managebac_calendar(content)

    def test_source_link_is_limited_to_secure_managebac_hosts(self):
        for url in (
            "javascript:alert(1)",
            "http://school.managebac.com/tasks/1",
            "https://evil.example/tasks/1",
            "https://user:pass@school.managebac.com/tasks/1",
        ):
            with self.subTest(url=url):
                content = f"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:unsafe-link@example.test\r
DTSTART;VALUE=DATE:20260910\r
SUMMARY:Task with unsafe source\r
CATEGORIES:Task\r
URL:{url}\r
END:VEVENT\r
END:VCALENDAR\r
""".encode("utf-8")
                parsed = parse_managebac_calendar(content)
                self.assertEqual(1, len(parsed.items))
                self.assertIsNone(parsed.items[0].source_url)

        credential_like = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:credential-link@example.test\r
DTSTART;VALUE=DATE:20260910\r
SUMMARY:Task with credential-like source\r
CATEGORIES:Task\r
URL:https://school.managebac.com/student/events/token/private.ics\r
END:VEVENT\r
END:VCALENDAR\r
"""
        self.assertIsNone(parse_managebac_calendar(credential_like).items[0].source_url)

        query_link = b"""BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
UID:query-link@example.test\r
DTSTART;VALUE=DATE:20260910\r
SUMMARY:Task with safe source\r
CATEGORIES:Task\r
URL:https://school.managebac.com/student/tasks/1?secret=value#fragment\r
END:VEVENT\r
END:VCALENDAR\r
"""
        self.assertEqual(
            "https://school.managebac.com/student/tasks/1",
            parse_managebac_calendar(query_link).items[0].source_url,
        )


if __name__ == "__main__":
    unittest.main()
