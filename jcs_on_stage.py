"""Only £25 On-stage Standing, future Drury Lane dates through 31 October.

Uses the official calendar and the separate stage ticket modal in ordinary
Chrome. Opens a ticket-area dialog only; never changes quantity, selects an
actual ticket, updates a basket, logs in, or accepts a standing agreement.
"""
import re
import json
import time
from datetime import datetime

import monitor
from golden_boy import Browser

SHOW = "https://lwtheatres.co.uk/whats-on/jesus-christ-superstar-trdl/"
CALENDAR = "https://ticketing.lwtheatres.co.uk/event/74991?date=2026-10"
END = datetime(2026, 11, 1, tzinfo=monitor.LONDON)
STATE_PATH = "jcs-on-stage-state.json"
NAME = "JCS《Jesus Christ Superstar》£25 On-Stage Standing · 10月31日及之前"
AREA = "On-stage Standing Tickets £25"

CALENDAR_DOM = r"""
return {url:location.href,title:document.title,text:document.body.innerText.slice(0,7000),
 month:document.querySelector('h2')?.textContent||'',
 slots:Array.from(document.querySelectorAll('.time-slot-tile')).map((e,index)=>({index,day:e.parentElement.querySelector('span')?.textContent||'',time:e.querySelector('span')?.textContent||'',text:e.innerText,disabled:e.getAttribute('aria-disabled')==='true'}))};
"""

STAGE_DOM = r"""
const heading=Array.from(document.querySelectorAll('h1')).find(h=>h.textContent.trim()==='On-stage Standing Tickets £25');
const root=heading?.closest('[data-g-portal-id]');
const usable=e=>!e.disabled && e.getAttribute('aria-disabled')!=='true' && e.getClientRects().length>0;
return {url:location.href,title:document.title,pageText:document.querySelector('.theme-wrapper')?.innerText.slice(0,2500)||'',
 heading:heading?.textContent||'',text:root?.innerText||'',
 selects:root?Array.from(root.querySelectorAll('select')).filter(usable).map(e=>({name:(e.name||'')+' '+(e.id||'')+' '+Array.from(e.labels||[]).map(l=>l.textContent).join(' '),options:Array.from(e.options).filter(o=>!o.disabled).map(o=>({value:o.value,text:o.textContent}))})):[],
 buttons:root?Array.from(root.querySelectorAll('button')).filter(usable).map(e=>({text:e.innerText,label:e.getAttribute('aria-label')||''})):[]};
"""


def parse_calendar(data, now):
    if "Jesus Christ Superstar" not in data.get("title", "") or "Theatre Royal Drury Lane" not in data.get("text", "") or data.get("month", "").strip() != "October 2026":
        raise monitor.MonitorError("LW calendar production/venue/month could not be verified")
    raw = data.get("slots")
    if not isinstance(raw, list) or not raw:
        raise monitor.MonitorError("LW calendar empty; not evidence of sold-out stage tickets")
    result, seen = [], set()
    for item in raw:
        match = re.fullmatch(r"(\d{1,2}):(\d{2})(am|pm)", item.get("time", "").strip(), re.I)
        day = item.get("day", "")
        if not match or not re.fullmatch(r"\d{1,2}", day):
            raise monitor.MonitorError("Unrecognised LW calendar performance time")
        hour = int(match[1]) % 12 + (12 if match[3].lower() == "pm" else 0)
        try:
            start = datetime(2026, 10, int(day), hour, int(match[2]), tzinfo=monitor.LONDON)
        except ValueError as exc:
            raise monitor.MonitorError("Invalid LW calendar performance date") from exc
        if start.isoformat() in seen:
            raise monitor.MonitorError("Duplicate LW calendar performance")
        seen.add(start.isoformat())
        if now < start < END:
            # Even when regular seats show £25, inspect the stage modal itself.
            # A disabled calendar tile cannot be followed/verified, so fail
            # honestly instead of treating that broad event state as stage stock.
            if item.get("disabled"):
                raise monitor.MonitorError("Requested future LW performance cannot be opened")
            result.append(dict(item, start=start.isoformat(), when=start.strftime("%Y-%m-%d %H:%M")))
    if not result:
        raise monitor.MonitorError("No future performances through 31 October returned")
    return result


def classify_stage(slot, data):
    url = data.get("url", "")
    if not re.fullmatch(r"https://ticketing\.lwtheatres\.co\.uk/event/74991/performance/\d+/?", url):
        raise monitor.MonitorError("Unexpected JCS performance booking URL")
    start = monitor.date(slot["start"]).astimezone(monitor.LONDON)
    expected_date = f"{start:%A} {start.day} October 2026, {start.hour % 12 or 12:02}:{start.minute:02} {'PM' if start.hour >= 12 else 'AM'}"
    if "Jesus Christ Superstar" not in data.get("title", "") or "Theatre Royal Drury Lane" not in data.get("pageText", "") or expected_date not in data.get("pageText", ""):
        raise monitor.MonitorError("JCS selected performance date/time/venue does not match")
    if data.get("heading", "").strip() != AREA:
        raise monitor.MonitorError("The £25 On-stage Standing ticket area is not verified")
    text = data.get("text", "")
    if "No tickets available" in text and "There are no tickets available for this performance" in text:
        return None
    if monitor.restricted(text):
        return None
    item = {"key": slot["start"] + "|" + url + "|on-stage-gbp25", "url": url, "when": slot["when"], "start": slot["start"], "price": "£25"}
    # A named ticket price plus a positive quantity control are both required.
    # The static modal heading and the ordinary £25 legend are insufficient.
    prices = re.findall(r"£\s*(\d+(?:\.\d{1,2})?)", text.replace(AREA, "", 1))
    price = any(float(p) == 25 for p in prices)
    quantity = any(str(o.get("value", "")).isdigit() and int(o["value"]) > 0 for s in data.get("selects", []) for o in s.get("options", []))
    increment = any(re.search(r"increase|increment|add (?:one|ticket)|plus", b.get("label", ""), re.I) for b in data.get("buttons", []))
    if price and (quantity or increment):
        return dict(item, confirmed=True, minimum_count=1)
    raise monitor.MonitorError("Stage ticket area opened but public £25 quantity is unconfirmed")


class LWBrowser(Browser):
    def script(self, code):
        return self.call(f"/session/{self.session}/execute/sync", "POST", {"script": code, "args": []})

    def elements(self, selector):
        return self.call(f"/session/{self.session}/elements", "POST", {"using": "css selector", "value": selector})

    @staticmethod
    def element_id(item):
        return item["element-6066-11e4-a52e-4f735466cecf"]

    def click(self, item):
        self.call(f"/session/{self.session}/element/{self.element_id(item)}/click", "POST", {})

    def reject_cookies(self):
        # Use the same ordinary settings buttons as a person; no injected consent.
        settings = self.elements('#onetrust-pc-btn-handler')
        if settings:
            visible = self.script("const e=document.querySelector('#onetrust-pc-btn-handler'); return Boolean(e&&e.getClientRects().length);")
            if visible:
                self.click(settings[0])
                for _ in range(10):
                    buttons = self.call(f"/session/{self.session}/elements", "POST", {"using": "xpath", "value": "//button[normalize-space()='Reject All']"})
                    if buttons:
                        self.click(buttons[0])
                        return
                    time.sleep(.2)

    def calendar(self, first=False):
        if first:
            self.call(f"/session/{self.session}/url", "POST", {"url": CALENDAR})
        else:
            self.call(f"/session/{self.session}/back", "POST", {})
        for _ in range(80):
            data = self.script(CALENDAR_DOM)
            if data.get("slots") and "Jesus Christ Superstar" in data.get("title", ""):
                self.reject_cookies()
                return data
            time.sleep(.4)
        print("LW load diagnostic:", json.dumps({"url": data.get("url"), "title": data.get("title"), "text": data.get("text", "")[:900]}, ensure_ascii=False))
        raise monitor.MonitorError("LW official calendar did not load; no CAPTCHA bypass")

    def read_stage(self, slot):
        current = self.script(CALENDAR_DOM)
        matches = [s for s in current.get("slots", []) if (s.get("day"), s.get("time")) == (slot["day"], slot["time"])]
        if len(matches) != 1:
            raise monitor.MonitorError("LW calendar changed during this check")
        elements = self.elements('.time-slot-tile')
        self.click(elements[matches[0]["index"]])
        for _ in range(40):
            buttons = self.elements('[role="button"][aria-label="On-stage Standing Tickets £25"]')
            if buttons:
                # The SVG area's mouse click does not reliably open its modal;
                # its public Enter handler is supported and was live-tested.
                self.call(f"/session/{self.session}/element/{self.element_id(buttons[0])}/value", "POST", {"text": "\ue007"})
                break
            time.sleep(.4)
        else:
            raise monitor.MonitorError("Official stage ticket area did not load")
        for _ in range(40):
            data = self.script(STAGE_DOM)
            text = data.get("text", "")
            if data.get("heading") and "Loading" not in text and ("No tickets available" in text or data.get("selects") or len(data.get("buttons", [])) > 2):
                return data
            time.sleep(.3)
        raise monitor.MonitorError("Official stage ticket quantities did not load")


def observe(now, on_candidates=None):
    available = []
    with LWBrowser() as browser:
        slots = parse_calendar(browser.calendar(first=True), now)
        for index, slot in enumerate(slots):
            if index:
                browser.calendar()
            item = classify_stage(slot, browser.read_stage(slot))
            print("JCS stage area checked:", slot["when"], "available" if item else "sold_out")
            if item:
                available.append(item)
    if on_candidates is not None:
        on_candidates(available)
    return {"total": len(slots), "available": available, "source": "official_lw_drury_lane_each_25_pound_stage_ticket_modal"}


def alert_body(items, now):
    lines = ["Theatre Royal Drury Lane《Jesus Christ Superstar》的 **£25 On-Stage Standing 舞台站票**已核实。", "", f"核验时间：{now.astimezone(monitor.LONDON):%Y-%m-%d %H:%M:%S}（伦敦时间）"]
    lines += [f"\n- **{item['when']}（伦敦时间）**：至少 1 张 £25 舞台站票；[官方购票页]({item['url']})，打开票图上方 On-stage Standing Tickets £25 票区。" for item in items]
    lines += ["", "仅筛选10月31日及之前的未来场次。£25为页面票价，结账如有额外费用请自行核对。余票随时可能售出。监控未改变数量、未加入购物车、未接受站票协议、未购买。"]
    return "\n".join(lines)


def run():
    monitor.run(config={"name": NAME, "prefix": "jcs-on-stage", "url": SHOW, "end": END, "format_alert": alert_body}, observer=observe, github=lambda: monitor.GitHub(STATE_PATH))


if __name__ == "__main__":
    run()
