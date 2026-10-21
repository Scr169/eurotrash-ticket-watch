"""One requested An Oak Tree performance, using official public Spektrix data.

The official calendar's dsp=2f895a240703 and its embedded ticketing iframe
were independently read: An Oak Tree, Sunday 15 November 2026, 15:00.
The official cast list identifies Suranne Jones on that date. No login/cart.
"""
from datetime import datetime
from urllib.parse import urlencode

import monitor

SHOW = "https://theotherpalace.co.uk/an-oak-tree/"
BOOKING = "https://theotherpalace.co.uk/choose-seats/?dsp=2f895a240703"
API = "https://system.spektrix.com/theotherpalace/api/v3"
EVENT_ID = "104401ANKRNNLHCVDTNJGJHJRJPJMRLCG"
INSTANCE_ID = "240703ASRQGGVGGHTHTRHBRGMPRRGJRMH"
START = datetime(2026, 11, 15, 15, tzinfo=monitor.LONDON)
END = START
STATE_PATH = "an-oak-tree-state.json"
NAME = "The Other Palace《An Oak Tree》Suranne Jones · 11月15日15:00"


def parse_source(events, instances, inventory, now):
    if not isinstance(events, list) or len(events) != 1:
        raise monitor.MonitorError("An Oak Tree production is missing or ambiguous")
    event = events[0]
    if (event.get("id"), event.get("name"), event.get("webEventId"), event.get("attribute_Venue")) != (EVENT_ID, "An Oak Tree", "OAK26", "Main House"):
        raise monitor.MonitorError("The Other Palace production identity changed")
    if not isinstance(instances, list) or len(instances) != 1:
        raise monitor.MonitorError("Requested Suranne Jones performance missing or ambiguous")
    item = instances[0]
    if item.get("id") != INSTANCE_ID or item.get("event", {}).get("id") != EVENT_ID or monitor.date(item.get("start")) != START:
        raise monitor.MonitorError("Not the requested 15 November 15:00 performance")
    if item.get("cancelled") is True:
        raise monitor.MonitorError("Requested performance is cancelled; do not report sold out")
    if type(item.get("isOnSale")) is not bool:
        raise monitor.MonitorError("Missing public sale status")
    rows = inventory.get("data") if isinstance(inventory, dict) else None
    if not isinstance(rows, list) or len(rows) != 1:
        raise monitor.MonitorError("Requested performance has no explicit inventory")
    row = rows[0]
    if row.get("eventInstanceId") != INSTANCE_ID or monitor.date(row.get("start")) != START:
        raise monitor.MonitorError("Inventory date/identity mismatch")
    bands = row.get("availability")
    if not isinstance(bands, list) or not bands:
        raise monitor.MonitorError("Missing explicit price-band seat counts")
    available = 0
    for band in bands:
        if band.get("status") not in {"Available", "Unavailable"}:
            raise monitor.MonitorError("Unexpected non-public inventory status")
        seats = monitor.count(band.get("count"))
        if band["status"] == "Available":
            available += seats
    selling = item["isOnSale"] and monitor.date(item.get("startSellingAtWebUtc")) <= now < monitor.date(item.get("stopSellingAtWebUtc"))
    candidate = {"key": START.isoformat() + "|" + BOOKING, "when": "2026-11-15 15:00", "url": BOOKING, "instance_id": INSTANCE_ID}
    return [candidate] if available and selling and not monitor.restricted(str(item)) else []


def observe(now, on_candidates=None):
    events = monitor.request_json(API + "/events?" + urlencode({"name": "An Oak Tree"}))
    # Spektrix's actual client response excludes start_to at midnight, so use
    # the next day then strictly require the single requested datetime above.
    query = "?start_from=2026-11-15&start_to=2026-11-16"
    base = API + "/events/" + EVENT_ID
    candidates = parse_source(events, monitor.request_json(base + "/instances" + query), monitor.request_json(base + "/availability" + query), now)
    if on_candidates is not None:
        on_candidates(candidates)
    available = []
    for candidate in candidates:
        status = monitor.request_json(API + "/instances/" + INSTANCE_ID + "/status?includeChildPlans=true")
        confirmed = monitor.confirm_public_seats(candidate, status)
        if confirmed:
            available.append(confirmed)
    return {"total": 1, "available": available, "source": "official_other_palace_spektrix_exact_suranne_performance"}


def alert_body(items, now):
    lines = [NAME + " 官方公开座位已核实。", "", f"核验时间：{now.astimezone(monitor.LONDON):%Y-%m-%d %H:%M:%S}（伦敦时间）"]
    lines += [f"\n- **{item['when']}（伦敦时间）**：核验时 {item['count']} 张普通公开座位；[官方购票页]({item['url']})" for item in items]
    lines += ["", "票价未知，请在售票页核对。余票随时可能售出。演员安排以剧院最新公告为准。监控不占座、不加购物车、不购买。"]
    return "\n".join(lines)


def run():
    monitor.run(config={"name": NAME, "prefix": "an-oak-tree", "url": SHOW, "end": END, "format_alert": alert_body}, observer=observe, github=lambda: monitor.GitHub(STATE_PATH))


if __name__ == "__main__":
    run()
