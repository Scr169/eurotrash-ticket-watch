"""Free, unattended Eurotrash monitor for a dedicated GitHub repository.

Uses GitHub's bot notifications. No email passwords or paid services required.
Reads only Young Vic's public Eurotrash data and never reserves/buys tickets.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SHOW = "https://www.youngvic.org/whats-on/eurotrash/"
API = "https://www.youngvic.org/api/attendable/v1/instances/?" + urlencode({
    "limit": "1000",
    "fields": "title,status,accessible_seating_available,duration,booking_url,start_datetime,end_datetime,notes,event_title,instance_types,access_types,venue,venue_display_name,tags",
    "order": "start_datetime", "child_of": "111",
})
LONDON = ZoneInfo("Europe/London")
END = datetime(2027, 1, 10, tzinfo=LONDON)
STATE_PATH = "monitor-state.json"


class MonitorError(Exception):
    pass


def request_json(url, method="GET", data=None, token=None, timeout=40):
    headers = {"Accept": "application/json", "User-Agent": "EurotrashAvailabilityMonitor/1.0"}
    if token:
        headers.update(Authorization=f"Bearer {token}", **{"X-GitHub-Api-Version": "2022-11-28"})
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=None if data is None else json.dumps(data).encode(), headers=headers, method=method)
    with urlopen(req, timeout=timeout) as response:
        raw = response.read(4_000_000)
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise MonitorError("Source returned a non-JSON page; availability is unknown") from exc


def booking_url(value):
    url = urljoin(SHOW, str(value or ""))
    parsed = urlparse(url)
    if not value or parsed.scheme != "https" or not (parsed.hostname or "").endswith(".youngvic.org"):
        raise MonitorError("Missing or unexpected official booking link")
    return url


def restricted(text):
    return bool(re.search(r"press[\s_-]*night|invitation[\s_-]*only|members?[\s_-]*only|access[\s_-]*only", text, re.I))


def parse_api(payload, now):
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items or len(items) > 1000:
        raise MonitorError("Official performance list is empty or invalid")
    available, total = [], 0
    for item in items:
        title = str(item.get("event_title") or item.get("title") or "")
        if "eurotrash" not in title.lower():
            raise MonitorError("Performance data does not identify Eurotrash")
        try:
            start = datetime.fromisoformat(item["start_datetime"].replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=LONDON)
        except (ValueError, KeyError, TypeError) as exc:
            raise MonitorError("Unrecognised performance date") from exc
        if start <= now or start >= END:
            continue
        total += 1
        status = item.get("status")
        if not isinstance(status, str) or not status:
            raise MonitorError("Missing ticket status")
        # These are the exact disabled-status codes used by Young Vic's own
        # instance-list component. SDO + accessible_seating_available is still
        # excluded: the remaining seats are reserved for Access customers.
        if status in {"SDO", "CAN"} or restricted(json.dumps(item.get("instance_types", [])) + str(item.get("notes", ""))):
            continue
        url = booking_url(item.get("booking_url"))
        available.append({"key": f"{start.isoformat()}|{url}", "when": start.astimezone(LONDON).strftime("%Y-%m-%d %H:%M"), "url": url, "confirmed": False})
    if not total:
        raise MonitorError("No future Eurotrash performances were returned")
    return {"total": total, "available": available, "source": "official_api"}


DOM_READ = r"""
const root = document.querySelector('#instance-list[data-event-id="111"]');
return {
 title: document.querySelector('h1')?.textContent || document.title,
 rows: Array.from(root?.querySelectorAll('.c-instance__event-details-item') || []).map(row => ({
  date: row.closest('.c-instance--event-group')?.querySelector('.c-instance__event-date')?.textContent || '',
  time: row.querySelector('.c-instance__list-time')?.textContent || '',
  text: row.textContent || '',
  disabled: row.querySelector('.c-btn--disabled')?.textContent || '',
  links: Array.from(row.querySelectorAll('.c-instance__event-booking a[href]')).map(a => ({
   text:a.textContent || '', url:a.href,
   disabled:a.getAttribute('aria-disabled') === 'true' || a.classList.contains('c-btn--disabled')
  }))
 })),
 challenge: /just a moment|verify you are human|access denied/i.test(document.title)
};
"""


class Browser:
    """Drive the Chrome/ChromeDriver already supplied by GitHub's Linux image."""
    def __enter__(self):
        driver = shutil.which("chromedriver")
        if not driver:
            raise MonitorError("Cloud image does not provide ChromeDriver")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}"
        self.process = subprocess.Popen([driver, f"--port={port}", "--silent"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.session = None
        for _ in range(50):
            try:
                self.call("/status")
                break
            except (URLError, OSError):
                time.sleep(.1)
        options = {"args": ["--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1280,1000"]}
        chrome = shutil.which("google-chrome") or shutil.which("google-chrome-stable")
        if chrome:
            options["binary"] = chrome
        result = self.call("/session", "POST", {"capabilities": {"alwaysMatch": {"browserName": "chrome", "goog:chromeOptions": options}}})
        self.session = result["sessionId"]
        return self

    def call(self, path, method="GET", data=None):
        result = request_json(self.base + path, method, data, timeout=55)
        value = result.get("value")
        if isinstance(value, dict) and value.get("error"):
            raise MonitorError("Browser: " + str(value.get("message", value["error"]))[:300])
        return value

    def navigate(self, url):
        self.call(f"/session/{self.session}/url", "POST", {"url": url})

    def read(self, script):
        return self.call(f"/session/{self.session}/execute/sync", "POST", {"script": script, "args": []})

    def __exit__(self, *args):
        try:
            if self.session:
                self.call(f"/session/{self.session}", "DELETE")
        finally:
            self.process.terminate()
            self.process.wait(timeout=10)


def parse_dom(data, now):
    if data.get("challenge"):
        raise MonitorError("Official site requires human verification; no CAPTCHA was solved")
    if "eurotrash" not in data.get("title", "").lower() or not data.get("rows"):
        raise MonitorError("Eurotrash performance list has not loaded")
    available, total = [], 0
    months = {"nov": 11, "dec": 12, "jan": 1}
    for row in data["rows"]:
        dm = re.search(r"(\d{1,2})\s*(Nov|Dec|Jan)", row.get("date", ""), re.I)
        tm = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", row.get("time", ""), re.I)
        if not dm or not tm:
            raise MonitorError("Performance date/time format changed")
        month = months[dm[2].lower()]
        hour = int(tm[1]) % 12 + (12 if tm[3].upper() == "PM" else 0)
        start = datetime(2027 if month == 1 else 2026, month, int(dm[1]), hour, int(tm[2]), tzinfo=LONDON)
        if start <= now or start >= END:
            continue
        total += 1
        if re.search(r"sold\s*out|cancelled", row.get("disabled", ""), re.I) or restricted(row.get("text", "")):
            continue
        links = [link for link in row.get("links", []) if not link.get("disabled") and not re.search(r"sold\s*out|access|member|waiting", link.get("text", ""), re.I)]
        if not links:
            # SDO + accessible seats has an enabled link labelled Sold Out.
            if any(re.search(r"sold\s*out|access|member|waiting", link.get("text", ""), re.I) for link in row.get("links", [])):
                continue
            raise MonitorError("A performance has no identifiable ticket status")
        url = booking_url(links[0]["url"])
        available.append({"key": f"{start.isoformat()}|{url}", "when": start.strftime("%Y-%m-%d %H:%M"), "url": url, "confirmed": False})
    if not total:
        raise MonitorError("No future Eurotrash performances were read")
    return {"total": total, "available": available, "source": "official_browser"}


def observe(now):
    try:
        return parse_api(request_json(API), now)
    except (MonitorError, HTTPError, URLError, TimeoutError, OSError) as api_error:
        print("Direct API unavailable; trying the official page in Chrome:", str(api_error)[:180])
    with Browser() as browser:
        browser.navigate(SHOW)
        for _ in range(30):
            data = browser.read(DOM_READ)
            if data.get("challenge"):
                raise MonitorError("Official site requires human verification")
            if data.get("rows"):
                return parse_dom(data, now)
            time.sleep(1)
    raise MonitorError("Dynamic Eurotrash performance list did not load in time")


class GitHub:
    def __init__(self):
        self.repo = os.environ["GITHUB_REPOSITORY"]
        self.token = os.environ["GH_TOKEN"]
        self.owner = os.environ.get("NOTIFY_USER") or self.repo.split("/")[0]
        if not re.fullmatch(r"[A-Za-z0-9-]+", self.owner):
            raise MonitorError("Invalid notification recipient")
        self.base = "https://api.github.com/repos/" + self.repo

    def call(self, path, method="GET", data=None):
        return request_json(self.base + path, method, data, self.token)

    def state(self):
        try:
            item = self.call("/contents/" + STATE_PATH)
        except HTTPError as exc:
            if exc.code == 404:
                return {}, None
            raise
        return json.loads(base64.b64decode(item["content"])), item["sha"]

    def save(self, state, sha):
        data = {"message": "Update monitor state [skip ci]", "content": base64.b64encode((json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()).decode()}
        if sha:
            data["sha"] = sha
        return self.call("/contents/" + STATE_PATH, "PUT", data)

    def notify(self, title, body, marker):
        # An alert may have been delivered immediately before a state-save
        # failure. Check the issue marker before creating a duplicate.
        for issue in self.call("/issues?state=all&per_page=100&sort=created&direction=desc"):
            if marker in (issue.get("body") or ""):
                return issue["html_url"]
        result = self.call("/issues", "POST", {"title": title, "body": f"@{self.owner}\n\n{body}\n\n<!-- {marker} -->", "assignees": [self.owner]})
        if not result.get("id"):
            raise MonitorError("GitHub did not acknowledge the alert")
        return result["html_url"]


def alert_body(items, now):
    lines = ["Young Vic 官网的 Eurotrash 场次出现公开购票入口。", "", f"核验时间：{now.astimezone(LONDON):%Y-%m-%d %H:%M:%S}（伦敦时间）", ""]
    for item in items:
        lines.append(f"- **{item['when']}（伦敦时间）**：[打开官方购票页]({item['url']})")
    lines.extend(["", "票价和实际可选座位请在官方售票页核对；余票可能随时被买走。监控只读取公开状态，不会替你订票。"])
    return "\n".join(lines)


def run():
    now = datetime.now(timezone.utc)
    if now >= END:
        print("Eurotrash has finished. No further ticket checks or alerts.")
        return
    gh = GitHub()
    state, sha = gh.state()
    before = json.dumps(state, sort_keys=True)
    stamp = now.isoformat()
    notification_error = None
    if os.environ.get("TEST_NOTIFICATION", "").lower() == "true":
        marker = "eurotrash-setup-test-" + os.environ.get("GITHUB_RUN_ID", stamp)
        url = gh.notify("【测试，不是放票】Eurotrash 云端通知测试", "这是 GitHub 云端监控发出的连接测试。**这不代表现在有票，也不代表查票链路已经通过验证。**\n\n若你收到这封邮件，邮件通知链路已连通。手机可开启 GitHub Mobile 的 Mentions／Assignments 推送，或 Gmail 新邮件通知。", marker)
        print("Test notification created:", url)
    try:
        observation = observe(now)
        items = observation["available"]
        old_keys = set(state.get("notified_keys", []))
        fresh = [item for item in items if item["key"] not in old_keys]
        if fresh:
            fingerprint = hashlib.sha256(json.dumps([i["key"] for i in fresh], sort_keys=True).encode()).hexdigest()[:20]
            episode = str(state.get("episode", 0) + 1)
            url = gh.notify("【购票入口恢复】Young Vic《Eurotrash》请立即核对余票", alert_body(fresh, now), "eurotrash-availability-" + episode + "-" + fingerprint)
            print("Availability notification acknowledged:", url)
            state["episode"] = int(episode)
        if state.get("failure_notice_sent"):
            gh.notify("【监控恢复】Eurotrash 云端查票恢复", f"已重新读取 Eurotrash 官方的 {observation['total']} 场未来演出。\n\n{SHOW}", "eurotrash-recovery-" + str(state.get("failure_episode", 0)))
        state.update(status="booking_reopened" if items else "sold_out", notified_keys=[item["key"] for item in items], consecutive_failures=0, failure_notice_sent=False, last_error=None, performance_count=observation["total"])
        print(json.dumps({"checked_at": stamp, "source": observation["source"], "performances": observation["total"], "bookable_signals": len(items), "status": state["status"]}))
    except Exception as exc:
        count = state.get("consecutive_failures", 0) + 1
        state.update(status="unknown", consecutive_failures=count, last_error=str(exc)[:500])
        print("::warning::Eurotrash availability could not be verified:", str(exc)[:250])
        if count >= 3 and not state.get("failure_notice_sent"):
            episode = state.get("failure_episode", 0) + 1
            try:
                gh.notify("【监控异常，不是放票】Eurotrash 连续读取失败", f"已连续 {count} 次无法核实官方余票，不能确认售罄或有票。\n\n错误：{str(exc)[:300]}\n\n请查看 [本次云端运行]({os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{gh.repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')})。\n\n{SHOW}", "eurotrash-failure-" + str(episode))
                state.update(failure_notice_sent=True, failure_episode=episode)
            except Exception as alert_exc:
                # Preserve the read-failure count even when notification itself
                # is unavailable, and retry the unsent notice on the next run.
                notification_error = alert_exc
                state["last_notification_error"] = str(alert_exc)[:300]
    # A small fortnightly state commit keeps GitHub's 60-day inactivity rule
    # from silently disabling the schedule before this production ends.
    heartbeat = datetime.fromisoformat(state.get("last_heartbeat", "2000-01-01T00:00:00+00:00"))
    if now - heartbeat >= timedelta(days=14):
        state["last_heartbeat"] = stamp
    if json.dumps(state, sort_keys=True) != before:
        state["last_state_change"] = stamp
        gh.save(state, sha)
    if notification_error is not None:
        raise MonitorError("Could not deliver the monitor failure notification") from notification_error


if __name__ == "__main__":
    run()
