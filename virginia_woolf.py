"""Read @sohoplace's official full-run calendar; verify positive links in Chrome.

The HTML's nlivenPerformances array is the data used by its visible calendar.
The nLiven series calendar's generic Low badge also appears on sold-out events,
so that badge and the evergreen Tickets button are never availability evidence.
"""
import json
import re
import time
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import monitor
from golden_boy import Browser

SHOW = "https://sohoplace.org/shows/whos-afraid-of-virginia-woolf-2026/"
STATE_PATH = "virginia-woolf-state.json"
END = datetime(2026, 12, 20, tzinfo=monitor.LONDON)
NAME = "@sohoplace《Who's Afraid of Virginia Woolf?》"


class Scripts(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inside = False
        self.scripts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.inside = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.inside = False

    def handle_data(self, data):
        if self.inside:
            self.scripts.append(data)


def normalise_title(text):
    return re.sub(r"[^a-z]", "", text.lower())


def parse_calendar(html, now):
    if "Who's Afraid of Virginia Woolf?" not in html and "Who’s Afraid of Virginia Woolf?" not in html:
        raise monitor.MonitorError("Official page no longer identifies Virginia Woolf")
    arrays = []
    for script in Scripts(html).scripts:
        match = re.search(r"\bconst\s+nlivenPerformances\s*=\s*", script)
        if match:
            try:
                value, _ = json.JSONDecoder().raw_decode(script[match.end():])
            except ValueError as exc:
                raise monitor.MonitorError("Official calendar is not valid JSON") from exc
            arrays.append(value)
    if len(arrays) != 1 or not isinstance(arrays[0], list) or not arrays[0]:
        raise monitor.MonitorError("Full-run official calendar missing or ambiguous")
    total, candidates, seen = 0, [], set()
    for row in arrays[0]:
        if not isinstance(row, dict) or row.get("product_id") != "23934" or normalise_title(row.get("name", "")) != "whosafraidofvirginiawoolf":
            raise monitor.MonitorError("Calendar contains another production")
        start = monitor.date(row.get("start_date_time"))
        if start.isoformat() in seen:
            raise monitor.MonitorError("Duplicate performance date")
        seen.add(start.isoformat())
        url = row.get("booking_url", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != "ticketing.sohoplace.org" or parsed.query or not re.fullmatch(r"/(?:shop/)?tickets/series/SPVWF01M/whos-afraid-of-virginia-woolf-" + re.escape(str(row.get("performance_id", ""))), parsed.path):
            raise monitor.MonitorError("Unexpected official performance booking URL")
        raw_count = row.get("availability")
        if not isinstance(raw_count, str) or not re.fullmatch(r"\d+", raw_count):
            raise monitor.MonitorError("No explicit official availability count")
        if not now < start < END:
            continue
        total += 1
        if not monitor.date(row.get("start_selling_at")) <= now < monitor.date(row.get("stop_selling_at")):
            continue
        if int(raw_count) and not monitor.restricted(row.get("description", "")):
            candidates.append({"key": start.isoformat() + "|" + url, "url": url, "start": start.isoformat(), "when": start.strftime("%Y-%m-%d %H:%M")})
    if not total:
        raise monitor.MonitorError("No future Virginia Woolf performances returned")
    return {"total": total, "candidates": candidates}


def read_calendar():
    request = Request(SHOW, headers={"Cache-Control": "no-cache", "User-Agent": "TheatreAvailabilityMonitor/1.0"})
    with urlopen(request, timeout=40) as response:
        return response.read(4_000_000).decode("utf-8")


BOOKING_DOM = r"""
const root = document.querySelector('[data-test="consumer-main-content"]');
const usable = e => !e.disabled && e.getAttribute('aria-disabled') !== 'true' && e.getClientRects().length > 0;
const restricted = s => /wheelchair|companion|members? only|access only|under.?25|under.?30/i.test(s);
const seats = root ? Array.from(root.querySelectorAll('[aria-label]')).filter(e=>{
 const label=e.getAttribute('aria-label')||'';
 const explicit=e.getAttribute('data-seat-status')==='available' || e.getAttribute('data-available')==='true' || /\bavailable\b/i.test(label);
 return usable(e) && explicit && /\bseat\b|\brow\b/i.test(label) && !/unavailable|not available/i.test(label) && !restricted(label);
}) : [];
return {url:location.href,title:document.title,heading:root?.querySelector('h1')?.textContent||'',
 selected:root?.querySelector('[data-test="view-series-event-list-event"].active')?.getAttribute('aria-label')||'',
 soldOut:Boolean(root?.querySelector('[data-test="sold-out"]')),text:(root?.innerText||'').slice(-20000),seatCount:seats.length};
"""


class SohoBrowser(Browser):
    def read(self, candidate):
        self.call(f"/session/{self.session}/url", "POST", {"url": candidate["url"]})
        for _ in range(25):
            data = self.call(f"/session/{self.session}/execute/sync", "POST", {"script": BOOKING_DOM, "args": []})
            if data.get("selected") and (data.get("soldOut") or data.get("seatCount") or "Loading Tickets" not in data.get("text", "")):
                return data
            time.sleep(1)
        raise monitor.MonitorError("Official nLiven booking page did not load; no CAPTCHA bypass")


def confirm_booking(candidate, data):
    if data.get("url", "").rstrip("/") != candidate["url"].rstrip("/") or normalise_title(data.get("heading", "")) != "whosafraidofvirginiawoolf":
        raise monitor.MonitorError("Booking page production/URL does not match")
    local = monitor.date(candidate["start"]).astimezone(monitor.LONDON)
    if local.strftime("%Y-%m-%dT%H:%M:%S") not in data.get("selected", ""):
        raise monitor.MonitorError("Booking page selected datetime does not match")
    if data.get("soldOut") is True:
        return None
    if monitor.restricted(data.get("text", "")):
        return None
    if monitor.count(data.get("seatCount")) > 0:
        return dict(candidate, minimum_count=1, confirmed=True)
    raise monitor.MonitorError("Official booking signal is open but no public selectable seat is confirmed")


def observe(now, on_candidates=None):
    result = parse_calendar(read_calendar(), now)
    if on_candidates is not None:
        on_candidates(result["candidates"])
    available = []
    if result["candidates"]:
        with SohoBrowser() as browser:
            for candidate in result["candidates"]:
                item = confirm_booking(candidate, browser.read(candidate))
                if item:
                    available.append(item)
    return {"total": result["total"], "available": available, "source": "official_sohoplace_full_run_calendar_and_booking_page"}


def alert_body(items, now):
    lines = [NAME + " 官方售票页已确认公开可选座位。", "", f"核验时间：{now.astimezone(monitor.LONDON):%Y-%m-%d %H:%M:%S}（伦敦时间）"]
    lines += [f"\n- **{item['when']}（伦敦时间）**：至少 1 张普通公开可选票；[官方购票页]({item['url']})" for item in items]
    lines += ["", "票价未知，请在售票页核对。余票随时可能售出。监控不占座、不加购物车、不购买。"]
    return "\n".join(lines)


def run():
    monitor.run(config={"name": NAME, "prefix": "virginia-woolf", "url": SHOW, "end": END, "format_alert": alert_body}, observer=observe, github=lambda: monitor.GitHub(STATE_PATH))


if __name__ == "__main__":
    run()
