import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import monitor

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
ITEM = {"booking_url": "https://book.youngvic.org/youngvic/website/ChooseSeats.aspx?EventInstanceId=50201&resize=true"}
INSTANCE_ID = "50201AJQJMNKPVNTVBTBMSCMBRSMTGJSS"
INSTANCE = {
    "id": INSTANCE_ID, "event": {"id": monitor.EVENT_ID},
    "start": "2026-11-13T19:30:00", "isOnSale": True,
    "cancelled": False,
    "startSellingAtWebUtc": "2026-04-23T10:30:00Z",
    "stopSellingAtWebUtc": "2026-11-13T19:15:00Z",
    "attribute_PerformanceInformation": "£12 first preview",
}
INVENTORY = {"data": [{
    "eventInstanceId": INSTANCE_ID, "start": INSTANCE["start"],
    "availability": [{"status": "Available", "count": 1}],
}]}


class AvailabilityTests(unittest.TestCase):
    def inventory(self, **changes):
        return monitor.parse_inventory([dict(INSTANCE, **changes)], INVENTORY, NOW)

    def test_event_lookup_excludes_programmes_and_other_shows(self):
        production = {"name": "EUROTRASH", "id": monitor.EVENT_ID, "attribute_SupplementaryEvent": False}
        programme = dict(production, name="Eurotrash programme", id="13201ABC", attribute_SupplementaryEvent=True)
        self.assertEqual(monitor.select_event([programme, production]), production)
        for events in [[programme], [dict(production, id="OTHER")], [], {}]:
            with self.subTest(events=events), self.assertRaises(monitor.MonitorError):
                monitor.select_event(events)

    def test_public_count_candidate_uses_documented_official_booking_link(self):
        result = self.inventory()
        self.assertEqual(result["total"], 1)
        item = result["candidates"][0]
        self.assertEqual(item["when"], "2026-11-13 19:30")
        self.assertEqual(item["url"], ITEM["booking_url"])
        self.assertNotIn("confirmed", item)

    def test_on_sale_does_not_mean_available(self):
        inventory = copy.deepcopy(INVENTORY)
        inventory["data"][0]["availability"][0]["count"] = 0
        self.assertEqual(monitor.parse_inventory([INSTANCE], inventory, NOW)["candidates"], [])

    def test_members_and_press_night_excluded(self):
        for text in ["Press Night", "Members only", "Access-only", "Invitation only"]:
            with self.subTest(text=text):
                self.assertEqual(self.inventory(attribute_PerformanceInformation=text)["candidates"], [])

    def test_public_sale_window_required_even_when_on_sale_is_true(self):
        self.assertEqual(self.inventory(startSellingAtWebUtc="2026-11-01T10:00:00Z")["candidates"], [])
        self.assertEqual(self.inventory(stopSellingAtWebUtc="2026-10-01T10:00:00Z")["candidates"], [])

    def test_wrong_show_empty_or_mismatched_inventory_is_error(self):
        for instances, payload in [([], INVENTORY), ([INSTANCE], {"data": []}), ([INSTANCE], {}), ([dict(INSTANCE, event={"id": "OTHER"})], INVENTORY), ([dict(INSTANCE, id="9999ABC")], INVENTORY), ([dict(INSTANCE, start="2026-11-14T19:30:00")], INVENTORY)]:
            with self.subTest(instances=instances), self.assertRaises(monitor.MonitorError):
                monitor.parse_inventory(instances, payload, NOW)

    def test_missing_negative_boolean_or_nonpublic_counts_are_errors(self):
        for invalid in [None, -1, True, "1"]:
            payload = copy.deepcopy(INVENTORY)
            payload["data"][0]["availability"][0]["count"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(monitor.MonitorError):
                monitor.parse_inventory([INSTANCE], payload, NOW)
        payload["data"][0]["availability"][0] = {"count": 1, "status": "Reserved"}
        with self.assertRaises(monitor.MonitorError):
            monitor.parse_inventory([INSTANCE], payload, NOW)

    def test_second_confirmation_excludes_access_and_eligibility_seats(self):
        candidate = self.inventory()["candidates"][0]
        status = {"available": 0, "wheelchairAvailable": 2, "specialAvailable": 3, "capacity": 564, "lockInfoAvailable": [{"quantity": 4}], "lockInfoSpecialAvailable": [{"quantity": 5}]}
        self.assertIsNone(monitor.confirm_public_seats(candidate, status))
        result = monitor.confirm_public_seats(candidate, dict(status, available=1))
        self.assertEqual(result["count"], 1)
        self.assertTrue(result["confirmed"])

    def test_january_last_day_is_included_and_finished_show_is_not(self):
        instance = dict(INSTANCE, start="2027-01-09T14:30:00", stopSellingAtWebUtc="2027-01-09T14:15:00Z")
        inventory = copy.deepcopy(INVENTORY)
        inventory["data"][0]["start"] = instance["start"]
        result = monitor.parse_inventory([instance], inventory, NOW)
        self.assertEqual(result["candidates"][0]["when"], "2027-01-09 14:30")
        with self.assertRaises(monitor.MonitorError):
            monitor.parse_inventory([instance], inventory, monitor.END)

    def test_notification_has_confirmed_quantity_and_explicit_unknown_price(self):
        candidate = self.inventory()["candidates"][0]
        item = monitor.confirm_public_seats(candidate, {"available": 2, "capacity": 564})
        body = monitor.alert_body([item], NOW)
        self.assertIn("2 张普通公开座位", body)
        self.assertIn("票价未知", body)
        self.assertIn("余票随时可能售出", body)

    def test_observation_checks_instance_again_before_notifying(self):
        production = {"name": "EUROTRASH", "id": monitor.EVENT_ID, "attribute_SupplementaryEvent": False}
        responses = [[production], [INSTANCE], INVENTORY, {"available": 0, "capacity": 564}]
        with patch.object(monitor, "request_json", side_effect=responses) as call:
            result = monitor.observe(NOW)
        self.assertEqual(result["available"], [])
        self.assertIn("/status?includeChildPlans=true", call.call_args_list[-1].args[0])

    def test_existing_issue_marker_prevents_duplicate_notification(self):
        with patch.dict("os.environ", {"GITHUB_REPOSITORY": "example/watch", "GH_TOKEN": "test"}):
            gh = monitor.GitHub()
        with patch.object(gh, "call", return_value=[{"body": "<!-- unique-marker -->", "html_url": "https://github.com/example/watch/issues/1"}]) as call:
            self.assertEqual(gh.notify("Test", "Body", "unique-marker"), "https://github.com/example/watch/issues/1")
            self.assertEqual(call.call_count, 1)


class StateTransitions(unittest.TestCase):
    def setUp(self):
        quiet = patch("builtins.print")
        quiet.start()
        self.addCleanup(quiet.stop)
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
        result = {"total": 58, "source": "fixture", "available": [{"key": "one", "when": "2026-11-14 19:30", "url": ITEM["booking_url"], "count": 1, "confirmed": True}] if available else []}
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
