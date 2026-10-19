import copy
from datetime import datetime, timezone
import unittest
from unittest.mock import patch

import golden_boy
import monitor

NOW = datetime(2026, 10, 18, 20, tzinfo=timezone.utc)
# Shape and disabled span taken from Almeida's actual calendar response.
ROW = '''<div class="c-calendar-instance">
<time datetime="2026-10-19 19:30:00">Mon 19 Oct 7.30pm</time>
<a class="c-calendar-instance__event-link" href="https://almeida.co.uk/whats-on/golden-boy/">
<h3 class="c-calendar-instance__title">Golden Boy</h3></a>
<div class="c-calendar-instance__button"><span class="c-btn c-btn--disabled">Sold Out</span></div></div>'''
PAYLOAD = {"filteredLabel": "Golden Boy", "instanceCount": 1, "instances": [ROW]}
CANDIDATE = {"url": "https://ticketing.almeida.co.uk/8745/8884", "start": "2026-10-19T19:30:00+01:00", "when": "2026-10-19 19:30", "key": "golden-test"}
PAGE = {"url": CANDIDATE["url"], "heading": "GOLDEN BOY, MONDAY 19 OCTOBER 2026 7:30PM", "text": "", "seatCount": 0, "selects": [], "purchaseControl": False}


class GoldenBoyTests(unittest.TestCase):
    def test_actual_disabled_span_is_sold_out_without_a_button(self):
        result = golden_boy.parse_calendar(PAYLOAD, NOW)
        self.assertEqual(result, {"total": 1, "candidates": []})

    def test_wrong_production_and_mismatched_count_are_errors(self):
        for payload in [dict(PAYLOAD, filteredLabel="NT Live Golden Boy"), dict(PAYLOAD, instanceCount=2), dict(PAYLOAD, instances=[]), dict(PAYLOAD, instances=[ROW.replace('>Golden Boy<', '>Another play<')])]:
            with self.subTest(payload=payload), self.assertRaises(monitor.MonitorError):
                golden_boy.parse_calendar(payload, NOW)

    def test_open_calendar_link_is_only_a_candidate(self):
        html = ROW.replace('<span class="c-btn c-btn--disabled">Sold Out</span>', '<a class="c-btn" href="https://ticketing.almeida.co.uk/8745/8884">Book Tickets</a>')
        result = golden_boy.parse_calendar(dict(PAYLOAD, instances=[html]), NOW)
        self.assertEqual(result["candidates"][0]["url"], CANDIDATE["url"])
        self.assertNotIn("confirmed", result["candidates"][0])

    def test_early_callback_happens_before_browser_launch_even_if_browser_fails(self):
        html = ROW.replace('<span class="c-btn c-btn--disabled">Sold Out</span>', '<a class="c-btn" href="https://ticketing.almeida.co.uk/8745/8884">Book Tickets</a>')
        seen = []
        with patch.object(golden_boy, 'read_calendar', return_value=dict(PAYLOAD, instances=[html])), patch.object(golden_boy, 'Browser', side_effect=monitor.MonitorError('browser failed')):
            with self.assertRaises(monitor.MonitorError):
                golden_boy.observe(NOW, on_candidates=lambda items: seen.extend(items))
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]['url'], CANDIDATE['url'])

    def test_spoofed_or_different_production_booking_links_rejected(self):
        for url in ['https://ticketing.almeida.co.uk.example.com/8745/8884', 'http://ticketing.almeida.co.uk/8745/8884', 'https://ticketing.almeida.co.uk/9999/8884', 'https://ticketing.almeida.co.uk/account/login']:
            with self.subTest(url=url), self.assertRaises(monitor.MonitorError):
                golden_boy.official_booking_url(url)

    def test_wrong_performance_cannot_confirm_stock(self):
        for page in [dict(PAGE, heading="GOLDEN BOY, TUESDAY 20 OCTOBER 2026 7:30PM"), dict(PAGE, url="https://ticketing.almeida.co.uk/8745/8885")]:
            with self.subTest(page=page), self.assertRaises(monitor.MonitorError):
                golden_boy.confirm_booking(CANDIDATE, page)

    def test_explicit_current_performance_sold_out_overrides_controls(self):
        page = dict(PAGE, text="Unfortunately this performance is sold out.", seatCount=3)
        self.assertIsNone(golden_boy.confirm_booking(CANDIDATE, page))

    def test_booking_button_without_public_seat_or_quantity_is_not_enough(self):
        with self.assertRaises(monitor.MonitorError):
            golden_boy.confirm_booking(CANDIDATE, dict(PAGE, purchaseControl=True))

    def test_eligible_only_price_does_not_confirm_public_tickets(self):
        selects = [{"name": "quantity", "options": [{"value": "1", "text": "1"}]}, {"name": "price zone", "options": [{"value": "12", "text": "Access companion £10"}]}]
        with self.assertRaises(monitor.MonitorError):
            golden_boy.confirm_booking(CANDIDATE, dict(PAGE, selects=selects, purchaseControl=True))

    def test_actual_selectable_seat_evidence_can_confirm_one_ticket(self):
        item = golden_boy.confirm_booking(CANDIDATE, dict(PAGE, seatCount=1))
        self.assertTrue(item["confirmed"])
        self.assertEqual(item["minimum_count"], 1)
        body = golden_boy.alert_body([item], NOW)
        self.assertIn('票价未知', body)
        self.assertIn('余票随时可能售出', body)

    def test_separate_github_state_file_preserves_eurotrash_state(self):
        with patch.dict('os.environ', {"GITHUB_REPOSITORY": "example/watch", "GH_TOKEN": "test"}):
            gh = monitor.GitHub(golden_boy.STATE_PATH)
        response = {"content": "e30=", "sha": "sha"}
        with patch.object(gh, 'call', return_value=response) as call:
            gh.state()
        self.assertEqual(call.call_args.args[0], '/contents/golden-boy-state.json')


if __name__ == '__main__':
    unittest.main()
