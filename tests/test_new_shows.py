import copy
import json
import unittest
from unittest.mock import patch

import monitor
import an_oak_tree as oak
import virginia_woolf as woolf
import jcs_on_stage as jcs


class OakTests(unittest.TestCase):
    def test_actual_target_sold_out(self):
        self.assertEqual(oak.parse_source(EVENTS, INSTANCES, INVENTORY, NOW), [])

    def test_empty_list_is_unknown(self):
        for events, instances, inventory in [(EVENTS, [], INVENTORY), (EVENTS, INSTANCES, {"data": []}), ([], INSTANCES, INVENTORY)]:
            with self.assertRaises(monitor.MonitorError):
                oak.parse_source(events, instances, inventory, NOW)

    def test_wrong_date_or_production_is_rejected(self):
        for field, value in [("start", "2026-11-14T15:00:00"), ("id", "240701NOTREQUESTED")]:
            items = copy.deepcopy(INSTANCES)
            items[0][field] = value
            with self.assertRaises(monitor.MonitorError):
                oak.parse_source(EVENTS, items, INVENTORY, NOW)

    def test_positive_stock_for_exact_date_only(self):
        stock = copy.deepcopy(INVENTORY)
        stock["data"][0]["availability"][0]["count"] = 1
        candidates = oak.parse_source(EVENTS, INSTANCES, stock, NOW)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["url"], oak.BOOKING)
        self.assertEqual(candidates[0]["when"], "2026-11-15 15:00")

    def test_wheelchair_or_eligibility_stock_is_not_public_confirmation(self):
        candidate = {"when": "2026-11-15 15:00", "url": oak.BOOKING}
        self.assertIsNone(monitor.confirm_public_seats(candidate, {"available": 0, "capacity": 307, "wheelchairAvailable": 1, "specialAvailable": 2}))


def page(row):
    return "<title>Who’s Afraid of Virginia Woolf?</title><script>const nlivenPerformances = " + json.dumps([row]) + "</script>"


class WoolfTests(unittest.TestCase):
    def test_official_zero_count_is_sold_out(self):
        self.assertEqual(woolf.parse_calendar(page(ROW), NOW), {"total": 1, "candidates": []})

    def test_evergreen_ticket_link_cannot_be_inventory(self):
        with self.assertRaises(monitor.MonitorError):
            woolf.parse_calendar("<title>Who's Afraid of Virginia Woolf?</title><a>Tickets from £40</a>", NOW)

    def test_member_link_and_wrong_production_are_rejected(self):
        for key, value in [("booking_url", ROW["booking_url"] + "?promo=WAC"), ("product_id", "other"), ("availability", "unknown")]:
            row = dict(ROW, **{key: value})
            with self.assertRaises(monitor.MonitorError):
                woolf.parse_calendar(page(row), NOW)

    def test_any_future_public_positive_count_is_candidate(self):
        row = dict(ROW, availability="1")
        result = woolf.parse_calendar(page(row), NOW)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["url"], ROW["booking_url"])

    def test_actual_nliven_low_badge_with_sold_out_notice_is_not_a_ticket(self):
        candidate = woolf.parse_calendar(page(dict(ROW, availability="1")), NOW)["candidates"][0]
        data = {"url": candidate["url"], "heading": "Who’s Afraid of Virginia Woolf?", "selected": "Select event Who's Afraid Of Virginia Woolf? on 2026-10-22T19:00:00", "soldOut": True, "text": "Low Performance Sold Out", "seatCount": 0}
        self.assertIsNone(woolf.confirm_booking(candidate, data))
        data["soldOut"] = False
        with self.assertRaises(monitor.MonitorError):
            woolf.confirm_booking(candidate, data)
        data["seatCount"] = 1
        self.assertTrue(woolf.confirm_booking(candidate, data)["confirmed"])

    def test_candidate_notice_precedes_slow_booking_check(self):
        calls = []
        class FakeBrowser:
            def __enter__(self):
                calls.append("browser")
                return self
            def __exit__(self, *args):
                return None
            def read(self, candidate):
                raise monitor.MonitorError("fixture blocked page")
        with patch.object(woolf, "read_calendar", return_value=page(dict(ROW, availability="1"))), patch.object(woolf, "SohoBrowser", FakeBrowser):
            with self.assertRaises(monitor.MonitorError):
                woolf.observe(NOW, on_candidates=lambda items: calls.append("notice"))
        self.assertEqual(calls, ["notice", "browser"])


class JCSTests(unittest.TestCase):
    def slot(self):
        data = {"title": "Choose your performance - Jesus Christ Superstar | LW Theatres", "text": "Theatre Royal Drury Lane", "month": "October 2026", "slots": [{"day": "27", "time": "7:30pm", "index": 0, "text": "7:30pm from £25.00", "disabled": False}]}
        return jcs.parse_calendar(data, NOW)[0]

    def data(self):
        return {"url": "https://ticketing.lwtheatres.co.uk/event/74991/performance/1126131", "title": "Select your tickets - Jesus Christ Superstar | LW Theatres", "pageText": "Theatre Royal Drury Lane Tuesday 27 October 2026, 07:30 PM", "heading": jcs.AREA, "text": jcs.AREA + "\nAdd tickets to your basket\nNo tickets available\nThere are no tickets available for this performance\nUpdate Basket", "selects": [], "buttons": []}

    def test_actual_regular_25_pound_seats_with_stage_sold_out_do_not_alert(self):
        self.assertIsNone(jcs.classify_stage(self.slot(), self.data()))

    def test_static_stage_25_heading_is_not_quantity_evidence(self):
        data = self.data()
        data["text"] = jcs.AREA + "\nUpdate Basket"
        with self.assertRaises(monitor.MonitorError):
            jcs.classify_stage(self.slot(), data)

    def test_positive_stage_quantity_and_explicit_25_price_are_required(self):
        data = self.data()
        data.update(text=jcs.AREA + "\nAdult £25.00\nQuantity", selects=[{"options": [{"value": "0"}, {"value": "1"}]}])
        result = jcs.classify_stage(self.slot(), data)
        self.assertTrue(result["confirmed"])
        data["text"] = jcs.AREA + "\nAdult £35.00\nQuantity"
        with self.assertRaises(monitor.MonitorError):
            jcs.classify_stage(self.slot(), data)

    def test_wrong_date_venue_and_ordinary_ticket_area_are_not_accepted(self):
        for field, value in [("pageText", "Theatre Royal Drury Lane Tuesday 3 November 2026, 07:30 PM"), ("heading", "Balcony £25"), ("url", "https://ticketing.lwtheatres.co.uk/event/52584/performance/1126131")]:
            data = dict(self.data(), **{field: value})
            with self.assertRaises(monitor.MonitorError):
                jcs.classify_stage(self.slot(), data)

    def test_no_past_performance_and_no_november_calendar(self):
        data = {"title": "Jesus Christ Superstar", "text": "Theatre Royal Drury Lane", "month": "October 2026", "slots": [{"day": "20", "time": "7:30pm", "index": 0}]}
        with self.assertRaises(monitor.MonitorError):
            jcs.parse_calendar(data, NOW)
        data["month"] = "November 2026"
        with self.assertRaises(monitor.MonitorError):
            jcs.parse_calendar(data, NOW)

NOW = monitor.date("2026-10-21T22:25:00Z")
EVENTS = json.loads('[{"description": "A rare chance to see the play that shaped a theatre landscape. When it opened in 2005 Tim Crouch’s An Oak Tree changed the rules of the game, bringing into the centre of its action an actor who has neither seen nor read the play.\\r\\nIn a performance of controlled virtuosity, the playwright guides that actor through a story of loss, suggestion and the power of the mind.\\r\\nNo two shows are the same. Each ‘vividly celebrates the live, raw, communal experience of theatre’ (Financial Times). This is an audience experience like no other.", "htmlDescription": "<div id>\\r\\n\\r\\n</div>", "duration": 75, "imageUrl": "https://system.spektrix.com/theotherpalace/files/9551e4c6-9d34-46af-bfbb-b06836535f20.jpg", "isOnSale": true, "name": "An Oak Tree", "instanceDates": "7 October-15 November", "thumbnailUrl": "https://system.spektrix.com/theotherpalace/files/9551e4c6-9d34-46af-bfbb-b06836535f20-thumbnail.jpg", "webUrl": "", "webEventId": "OAK26", "id": "104401ANKRNNLHCVDTNJGJHJRJPJMRLCG", "firstInstanceDateTime": "2026-10-07T19:00:00", "firstInstanceDateTimeUtc": "2026-10-07T18:00:00Z", "lastInstanceDateTime": "2026-11-15T15:00:00", "lastInstanceDateTimeUtc": "2026-11-15T15:00:00Z", "altText": "a man\'s face partially obscured by a glass of water", "attribute_Age": "12+", "attribute_DontIncludeOnWhatsOn": false, "attribute_ThirdPartyListings": false, "attribute_Ticketsforgoodevent": false, "attribute_Venue": "Main House"}]')
INSTANCES = json.loads('[{"isOnSale": true, "planId": "4801ANHPDLLRCQPPBDBQTRQJMPNKSLKPJ", "priceList": {"id": "259401AJLBRVRQLQSBCNPSGRKJHSTSMBM"}, "event": {"id": "104401ANKRNNLHCVDTNJGJHJRJPJMRLCG"}, "start": "2026-11-15T15:00:00", "startUtc": "2026-11-15T15:00:00", "startSellingAtWeb": "2026-07-15T16:00:00", "startSellingAtWebUtc": "2026-07-15T15:00:00Z", "stopSellingAtWeb": "2026-11-15T14:30:00", "stopSellingAtWebUtc": "2026-11-15T14:30:00Z", "webInstanceId": null, "cancelled": false, "id": "240703ASRQGGVGGHTHTRHBRGMPRRGJRMH", "hasBestAvailableOverlay": false, "attribute_AudioDescribedPerformance": false, "attribute_CaptionedPerformance": false, "attribute_PostShowQAndASession": false, "attribute_PreShowDragPerformance": false, "attribute_RelaxedPerformance": false, "attribute_SignedPerformance": false, "attribute_SingalongPerformance": false, "attribute_Ticketsforgoodinstance": false, "attribute_UnderstudyPerformance": false}]')
INVENTORY = json.loads('{"data": [{"eventInstanceId": "240703ASRQGGVGGHTHTRHBRGMPRRGJRMH", "start": "2026-11-15T15:00:00", "startUtc": "2026-11-15T15:00:00Z", "capacity": 307, "startSellingForCustomer": "2026-07-15T16:00:00", "startSellingForCustomerUtc": "2026-07-15T15:00:00Z", "availability": [{"priceBand": "401ANPJQJQPQMRSBDNMVNLSPGTRBVQVRH", "status": "Available", "count": 0, "ticketTypes": []}, {"priceBand": "201AGBHDRLQHNHPHKKMPKLGPMDRDTDMVL", "status": "Available", "count": 0, "ticketTypes": []}, {"priceBand": "402AJKCLLRDNMBKMHTCGLBDHJTBPJBDNV", "status": "Available", "count": 0, "ticketTypes": []}]}]}')
ROW = json.loads('{"performance_id": "2020467", "product_id": "23934", "name": "Who\'s Afraid Of Virginia Woolf?", "description": "", "start_date_time": "2026-10-22 19:00:00", "availability": "0", "start_selling_at": "2026-03-08 00:00:00", "stop_selling_at": "2026-10-22 18:00:00", "booking_url": "https://ticketing.sohoplace.org/shop/tickets/series/SPVWF01M/whos-afraid-of-virginia-woolf-2020467"}')
