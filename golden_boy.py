"""Almeida Golden Boy monitor using the live official calendar.

The source URL and POST fields were read from Almeida's own calendar script
and form. Only reads public data; never selects a seat or adds to a basket.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime
from html.parser import HTMLParser
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

import monitor

SHOW = "https://almeida.co.uk/whats-on/golden-boy/"
CALENDAR = "https://almeida.co.uk/calendar/?e=golden-boy"
CALENDAR_API = "https://almeida.co.uk/admin/wp-admin/admin-ajax.php"
END = datetime(2026, 11, 1, tzinfo=monitor.LONDON)
STATE_PATH = "golden-boy-state.json"
PROBE = {"url": "https://ticketing.almeida.co.uk/8745/8884", "start": "2026-10-19T19:30:00+01:00"}


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return " ".join(" ".join(c.text() if isinstance(c, Node) else c for c in self.children).split())

    def find(self, *, tag=None, cls=None):
        result = []
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get("class", "").split()):
                    result.append(child)
                result.extend(child.find(tag=tag, cls=cls))
        return result


class Markup(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        # Almeida's response includes an extra </time>. Ignore unmatched ends.
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                self.stack = self.stack[:index]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def official_booking_url(value):
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != "ticketing.almeida.co.uk" or not re.fullmatch(r"/8745/\d+/?", parsed.path) or parsed.query:
        raise monitor.MonitorError("Unexpected Golden Boy booking link")
    return value


def parse_calendar(payload, now):
    if not isinstance(payload, dict) or payload.get("filteredLabel") != "Golden Boy":
        raise monitor.MonitorError("Calendar does not identify Golden Boy")
    instances = payload.get("instances")
    if not isinstance(instances, list) or not instances or type(payload.get("instanceCount")) is not int or len(instances) != payload["instanceCount"]:
        raise monitor.MonitorError("Empty or inconsistent official calendar")
    total, candidates, seen = 0, [], set()
    for html in instances:
        if not isinstance(html, str):
            raise monitor.MonitorError("Calendar row is not HTML")
        rows = Markup(html).root.find(cls="c-calendar-instance")
        if len(rows) != 1:
            raise monitor.MonitorError("Unrecognised calendar row layout")
        row = rows[0]
        titles = row.find(cls="c-calendar-instance__title")
        links = row.find(cls="c-calendar-instance__event-link")
        dates = row.find(tag="time")
        if len(titles) != 1 or titles[0].text().casefold() != "golden boy" or len(links) != 1 or links[0].attrs.get("href") != SHOW or len(dates) != 1:
            raise monitor.MonitorError("Calendar contains another event or an invalid date")
        start = monitor.date(dates[0].attrs.get("datetime"))
        if start.isoformat() in seen:
            raise monitor.MonitorError("Duplicate performance in calendar")
        seen.add(start.isoformat())
        if start <= now or start >= END:
            continue
        total += 1
        controls = row.find(cls="c-calendar-instance__button")
        if len(controls) != 1:
            raise monitor.MonitorError("Missing performance booking status")
        control = controls[0]
        disabled = control.find(cls="c-btn--disabled")
        if disabled:
            if not all(re.search(r"sold\s*out|cancelled", node.text(), re.I) for node in disabled):
                raise monitor.MonitorError("Unrecognised disabled booking status")
            continue
        if monitor.restricted(row.text()) or re.search(r"access tickets only|invited guests only", row.text(), re.I):
            continue
        booking_links = [a for a in control.find(tag="a") if a.attrs.get("aria-disabled") != "true" and not re.search(r"access|members?|waiting|sold\s*out", a.text(), re.I)]
        if len(booking_links) != 1:
            raise monitor.MonitorError("No unambiguous public booking link")
        url = official_booking_url(booking_links[0].attrs.get("href", ""))
        candidates.append({"key": start.isoformat() + "|" + url, "url": url, "start": start.isoformat(), "when": start.strftime("%Y-%m-%d %H:%M")})
    if not total:
        raise monitor.MonitorError("No future Golden Boy performances returned")
    return {"total": total, "candidates": candidates}


def read_calendar():
    data = urlencode({"action": "calendar", "filters": "event=11278&date_range="}).encode()
    request = Request(CALENDAR_API, data=data, headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded", "Cache-Control": "no-cache", "User-Agent": "TheatreAvailabilityMonitor/1.0"})
    with urlopen(request, timeout=40) as response:
        raw = response.read(4_000_000)
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise monitor.MonitorError("Official calendar returned non-JSON data") from exc


BOOKING_DOM = r"""
const h = document.querySelector('#tn-page-heading');
const root = document.querySelector('main') || document.body;
const text = root?.innerText || '';
const usable = e => !e.disabled && e.getAttribute('aria-disabled') !== 'true' && e.getClientRects().length > 0;
const restricted = s => /wheelchair|companion|members? only|access only|under.?25|under.?30/i.test(s);
const seats = Array.from(root.querySelectorAll('[role="button"][aria-label], button[aria-label], [data-seat-status], [data-available]')).filter(e => {
 const label = e.getAttribute('aria-label') || '';
 const available = e.getAttribute('data-seat-status') === 'available' || e.getAttribute('data-available') === 'true' || /\bavailable\b/i.test(label);
 return usable(e) && available && /\bseat\b|\brow\b/i.test(label) && !/unavailable|not available/i.test(label) && !restricted(label);
});
const selects = Array.from(root.querySelectorAll('select')).filter(usable).map(e => ({
 name: (e.name || '') + ' ' + (e.id || '') + ' ' + Array.from(e.labels || []).map(x=>x.textContent).join(' '),
 options: Array.from(e.options).filter(o=>!o.disabled).map(o=>({value:o.value,text:o.textContent || ''}))
}));
return {url:location.href, title:document.title, heading:h?.textContent || '', text:text.slice(0,50000), seatCount:seats.length, selects,
 purchaseControl: Array.from(root.querySelectorAll('button,input[type="submit"]')).filter(usable).some(e=>/add to (basket|cart)|select seats|choose seats/i.test(e.textContent || e.value || ''))};
"""


class Browser:
    def __enter__(self):
        driver = shutil.which("chromedriver")
        if not driver:
            raise monitor.MonitorError("Cloud ChromeDriver is unavailable")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        self.process = subprocess.Popen([driver, f"--port={port}", "--silent"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.session = None
        try:
            for _ in range(50):
                try:
                    self.call("/status")
                    break
                except (URLError, OSError):
                    time.sleep(.1)
            args = ["--no-sandbox", "--disable-dev-shm-usage", "--window-size=1280,1000"]
            if not os.environ.get("DISPLAY"):
                args.insert(0, "--headless=new")
            options = {"args": args}
            chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
            if chrome:
                options["binary"] = chrome
            self.session = self.call("/session", "POST", {"capabilities": {"alwaysMatch": {"browserName": "chrome", "goog:chromeOptions": options}}})["sessionId"]
            return self
        except Exception:
            self.process.terminate()
            self.process.wait(timeout=10)
            raise

    def call(self, path, method="GET", data=None):
        value = monitor.request_json(self.base + path, method, data, timeout=55).get("value")
        if isinstance(value, dict) and value.get("error"):
            raise monitor.MonitorError("Browser: " + str(value.get("message", value["error"]))[:200])
        return value

    def read(self, candidate):
        self.call(f"/session/{self.session}/url", "POST", {"url": candidate["url"]})
        data = {}
        for _ in range(30):
            data = self.call(f"/session/{self.session}/execute/sync", "POST", {"script": BOOKING_DOM, "args": []})
            if "golden boy" in data.get("heading", "").casefold():
                return data
            # Wait for normal loading only. Never interact with a CAPTCHA or
            # change browser fingerprints to evade a challenge.
            time.sleep(1)
        raise monitor.MonitorError("Official booking page did not load; may require human verification")

    def __exit__(self, *args):
        try:
            if self.session:
                self.call(f"/session/{self.session}", "DELETE")
        finally:
            self.process.terminate()
            self.process.wait(timeout=10)


def confirm_booking(candidate, data):
    if data.get("url", "").rstrip("/") != candidate["url"].rstrip("/"):
        raise monitor.MonitorError("Booking page redirected to a different performance")
    start = monitor.date(candidate["start"]).astimezone(monitor.LONDON)
    heading = re.sub(r"\s+", "", data.get("heading", "")).casefold()
    expected_day = f"{start.day}{start:%B%Y}".casefold()
    expected_time = f"{start.hour % 12 or 12}:{start.minute:02}{'pm' if start.hour >= 12 else 'am'}"
    if "goldenboy" not in heading or expected_day not in heading or expected_time not in heading:
        raise monitor.MonitorError("Booking page performance title/date does not match")
    text = data.get("text", "")
    if re.search(r"unfortunately this performance is sold out|this performance is no longer available", text, re.I):
        return None
    if monitor.restricted(text) or re.search(r"access tickets only|invited guests only", text, re.I):
        return None
    seats = monitor.count(data.get("seatCount"))
    quantity, price = False, False
    for select in data.get("selects", []):
        name = select.get("name", "")
        for option in select.get("options", []):
            label = option.get("text", "")
            if re.search(r"wheelchair|companion|members?|access|under.?25|under.?30", label, re.I):
                continue
            if re.search(r"quantity|qty|number.?of.?tickets|ticket.?count", name, re.I) and str(option.get("value", "")).isdigit() and int(option["value"]) > 0:
                quantity = True
            if re.search(r"price|ticket.?type|zone|section", name, re.I) and re.search(r"£\s*\d", label) and option.get("value"):
                price = True
    if seats or (quantity and price and data.get("purchaseControl") is True):
        return dict(candidate, confirmed=True, evidence="selectable_public_seat" if seats else "public_ticket_quantity_and_price", minimum_count=1)
    raise monitor.MonitorError("Booking link is open but no public selectable seat/quantity is confirmed")


def observe(now):
    result = parse_calendar(read_calendar(), now)
    available = []
    probe = os.environ.get("VERIFY_BOOKING_PROBE", "").lower() == "true"
    if result["candidates"] or probe:
        with Browser() as browser:
            if probe:
                confirm_booking(PROBE, browser.read(PROBE))
                print("Official Golden Boy booking-page connectivity verified (not a ticket alert).")
            for candidate in result["candidates"]:
                item = confirm_booking(candidate, browser.read(candidate))
                if item:
                    available.append(item)
    return {"total": result["total"], "available": available, "source": "official_almeida_calendar_and_booking_page"}


def alert_body(items, now):
    lines = ["Almeida《Golden Boy》官方售票页已出现公开可选票/座位。", "", f"核验时间：{now.astimezone(monitor.LONDON):%Y-%m-%d %H:%M:%S}（伦敦时间）", ""]
    for item in items:
        lines.append(f"- **{item['when']}（伦敦时间）**：核验时至少 1 张公开可选票；[官方直达购票页]({item['url']})")
    lines += ["", "票价未知，请在售票页核对。余票随时可能售出。监控不占座、不加入购物车、不购买。"]
    return "\n".join(lines)


def run():
    monitor.run(config={"name": "Almeida《Golden Boy》", "prefix": "golden-boy", "url": SHOW, "end": END, "format_alert": alert_body}, observer=observe, github=lambda: monitor.GitHub(STATE_PATH))


if __name__ == "__main__":
    run()
