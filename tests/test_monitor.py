import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import monitor

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
ITEM = {
    "event_title": "Eurotrash", "status": "LAV",
    "start_datetime": "2026-11-14T19:30:00Z",
    "booking_url": "https://tickets.youngvic.org/event/example",
    "instance_types": [], "notes": "",
}
ROW = {
    "date": "Sat14 Nov", "time": "7:30 PM", "text": "Main House",
    "disabled": "", "links": [{"text": "Book Now", "url": ITEM["booking_url"], "disabled": False}],
}


class AvailabilityTests(unittest.TestCase):
    def api(self, **changes):
        return monitor.parse_api({"items": [dict(ITEM, **changes)]}, NOW)

    def dom(self, **changes):
        return monitor.parse_dom({"title": "Eurotrash", "rows": [dict(ROW, **changes)]}, NOW)

    def test_public_limited_availability_returns_booking_link(self):
        result = self.api()
        self.assertEqual(result["available"][0]["when"], "2026-11-14 19:30")

    def test_access_reserved_seats_are_not_a_public_restock(self):
        self.assertEqual(self.api(status="SDO", accessible_seating_available=True)["available"], [])

    def test_cancelled_and_press_night_are_excluded(self):
        self.assertEqual(self.api(status="CAN")["available"], [])
        self.assertEqual(self.api(instance_types=[{"slug": "press-night"}])["available"], [])

    def test_wrong_show_empty_list_and_missing_status_are_errors(self):
        for payload in [{"items": []}, {"items": [dict(ITEM, event_title="Another show")]}, {"items": [dict(ITEM, status=None)]}]:
            with self.subTest(payload=payload), self.assertRaises(monitor.MonitorError):
                monitor.parse_api(payload, NOW)

    def test_untrusted_booking_hosts_are_rejected(self):
        for url in ["https://youngvic.org.example.com/ticket", "http://tickets.youngvic.org/event/1", "javascript:alert(1)"]:
            with self.subTest(url=url), self.assertRaises(monitor.MonitorError):
                self.api(booking_url=url)

    def test_dom_reads_group_date_and_public_booking_control(self):
        self.assertEqual(self.dom()["available"][0]["when"], "2026-11-14 19:30")

    def test_enabled_sold_out_access_link_is_excluded(self):
        self.assertEqual(self.dom(links=[dict(ROW["links"][0], text="Sold Out")])["available"], [])

    def test_disabled_span_means_sold_out(self):
        self.assertEqual(self.dom(disabled="Sold Out", links=[])["available"], [])

    def test_challenge_and_empty_dom_do_not_mean_sold_out(self):
        for data in [{"title": "Eurotrash", "rows": []}, {"title": "Just a moment...", "challenge": True, "rows": [ROW]}]:
            with self.subTest(data=data), self.assertRaises(monitor.MonitorError):
                monitor.parse_dom(data, NOW)

    def test_january_performance_uses_2027_and_matinee_time(self):
        result = self.dom(date="Sat9 Jan", time="2:30 PM")
        self.assertEqual(result["available"][0]["when"], "2027-01-09 14:30")

    def test_notification_does_not_claim_confirmed_seats_or_price(self):
        body = monitor.alert_body(self.api()["available"], NOW)
        self.assertIn("实际可选座位请在官方售票页核对", body)
        self.assertNotIn("£", body)

    def test_existing_issue_marker_prevents_duplicate_notification(self):
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "example/watch", "GH_TOKEN": "test"}):
            gh = monitor.GitHub()
        with patch.object(gh, "call", return_value=[{"body": "<!-- unique-marker -->", "html_url": "https://github.com/example/watch/issues/1"}]) as call:
            self.assertEqual(gh.notify("Test", "Body", "unique-marker"), "https://github.com/example/watch/issues/1")
            self.assertEqual(call.call_count, 1)


class StateTransitions(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        self.sent = []
        outer = self

        class FakeGitHub:
            repo = "example/watch"

            def state(self):
                return copy.deepcopy(outer.saved), "sha"

            def save(self, state, sha):
                outer.saved = copy.deepcopy(state)

            def notify(self, title, body, marker):
                if getattr(outer, "delivery_fails", False):
                    raise monitor.MonitorError("notification unavailable")
                outer.sent.append((title, marker))
                return "https://github.com/example/watch/issues/1"

        self.gh_patch = patch.object(monitor, "GitHub", FakeGitHub)
        self.gh_patch.start()
        self.clock = patch.object(monitor, "datetime", wraps=datetime)
        mocked_clock = self.clock.start()
        mocked_clock.now.return_value = NOW
        self.addCleanup(self.gh_patch.stop)
        self.addCleanup(self.clock.stop)

    def tick(self, available=False, fail=False):
        result = {"total": 58, "source": "fixture", "available": [{"key": "one", "when": "2026-11-14 19:30", "url": ITEM["booking_url"]}] if available else []}
        with patch.object(monitor, "observe", side_effect=monitor.MonitorError("source unavailable") if fail else None, return_value=result):
            monitor.run()

    def test_sold_out_round_stays_quiet(self):
        self.tick()
        self.assertEqual(self.sent, [])
        self.assertEqual(self.saved["status"], "sold_out")

    def test_continuous_stock_deduplicates_but_return_after_sold_out_alerts(self):
        self.tick(available=True)
        self.tick(available=True)
        self.assertEqual(len(self.sent), 1)
        self.tick()
        self.tick(available=True)
        self.assertEqual(len(self.sent), 2)
        self.assertNotEqual(self.sent[0][1], self.sent[1][1])

    def test_unacknowledged_alert_is_retried_not_marked_delivered(self):
        self.delivery_fails = True
        self.tick(available=True)
        self.assertEqual(self.saved.get("notified_keys", []), [])
        self.delivery_fails = False
        self.tick(available=True)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.saved["notified_keys"], ["one"])

    def test_third_failure_alerts_once_and_recovery_alerts_once(self):
        self.tick(fail=True)
        self.tick(fail=True)
        self.assertEqual(self.sent, [])
        self.tick(fail=True)
        self.tick(fail=True)
        self.assertEqual(len(self.sent), 1)
        self.tick()
        self.tick()
        self.assertEqual(len(self.sent), 2)
        self.assertIn("恢复", self.sent[1][0])

    def test_notification_failure_preserves_count_for_retry(self):
        self.delivery_fails = True
        self.tick(fail=True)
        self.tick(fail=True)
        with self.assertRaises(monitor.MonitorError):
            self.tick(fail=True)
        self.assertEqual(self.saved["consecutive_failures"], 3)
        self.assertFalse(self.saved.get("failure_notice_sent", False))
        self.delivery_fails = False
        self.tick(fail=True)
        self.assertTrue(self.saved["failure_notice_sent"])


if __name__ == "__main__":
    unittest.main()
