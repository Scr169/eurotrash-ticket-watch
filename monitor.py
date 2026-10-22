"""Free cloud monitor. Reads only Eurotrash's official public ticket API.

Spektrix Web-mode API documentation:
https://integrate.spektrix.com/docs/apieventfiltering
https://integrate.spektrix.com/docs/Availability
No login, personal credentials, reservations or purchases.
"""
import base64
import hashlib
import json
import os
import re
from datetime import datetime, timezone, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

SHOW = "https://www.youngvic.org/whats-on/eurotrash/"
TICKETS = "https://system.spektrix.com/youngvic/api/v3"
# Verified by the official public API: name EUROTRASH, Main House,
# starring Kathryn Hunter and Ben Whishaw, 13 Nov 2026–9 Jan 2027.
EVENT_ID = "10601APSKMRRDLKDGKBKNPNLTDRGCSHLR"
LONDON = ZoneInfo("Europe/London")
END = datetime(2027, 1, 10, tzinfo=LONDON)
STATE_PATH = "monitor-state.json"


class MonitorError(Exception):
    pass


def request_json(url, method="GET", data=None, token=None, timeout=40):
    headers = {"Accept": "application/json", "User-Agent": "EurotrashAvailabilityMonitor/1.0", "Cache-Control": "no-cache"}
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


def date(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=LONDON) if parsed.tzinfo is None else parsed
    except (ValueError, TypeError, AttributeError) as exc:
        raise MonitorError("Unrecognised official performance date") from exc


def count(value):
    if type(value) is not int or value < 0:
        raise MonitorError("Missing or invalid seat count")
    return value


def restricted(text):
    return bool(re.search(r"press[\s_-]*night|invitation[\s_-]*only|members?[\s_-]*only|access[\s_-]*only", text, re.I))


def select_event(events):
    if not isinstance(events, list):
        raise MonitorError("Official event list is invalid")
    matches = [e for e in events if e.get("name", "").strip().casefold() == "eurotrash" and e.get("id") == EVENT_ID and e.get("attribute_SupplementaryEvent") is False]
    if len(matches) != 1:
        raise MonitorError("Could not verify the Eurotrash production; programmes are excluded")
    return matches[0]


def parse_inventory(instances, inventory, now):
    """Require matching public instance metadata and explicit availability counts."""
    rows = inventory.get("data") if isinstance(inventory, dict) else None
    if not isinstance(instances, list) or not instances or not isinstance(rows, list) or not rows:
        raise MonitorError("Official performance or availability list is empty")
    by_id = {}
    for row in rows:
        instance_id = row.get("eventInstanceId")
        if not isinstance(instance_id, str) or instance_id in by_id:
            raise MonitorError("Invalid or duplicate availability instance")
        by_id[instance_id] = row
    candidates, total = [], 0
    for instance in instances:
        if instance.get("event", {}).get("id") != EVENT_ID:
            raise MonitorError("Availability includes a different production")
        start = date(instance.get("start"))
        if start <= now or start >= END or instance.get("cancelled") is True:
            continue
        if type(instance.get("isOnSale")) is not bool:
            raise MonitorError("Missing public sale status")
        if not instance["isOnSale"]:
            continue
        total += 1
        # Priority-booking attributes alone do not show current eligibility.
        # Check the actual public sale window instead, without authenticating.
        if date(instance.get("startSellingAtWebUtc")) > now or date(instance.get("stopSellingAtWebUtc")) <= now:
            continue
        if restricted(str(instance.get("attribute_PerformanceInformation", ""))):
            continue
        instance_id = instance.get("id", "")
        if not re.fullmatch(r"\d+[A-Z]+", instance_id):
            raise MonitorError("Invalid official instance ID")
        row = by_id.get(instance_id)
        if row is None or date(row.get("start")) != start:
            raise MonitorError("Availability is missing or has a mismatched date")
        bands = row.get("availability")
        if not isinstance(bands, list) or not bands:
            raise MonitorError("Availability has no price-band counts")
        available = 0
        for band in bands:
            if band.get("status") not in {"Available", "Unavailable"}:
                raise MonitorError("Unexpected non-public inventory status")
            seats = count(band.get("count"))
            if band["status"] == "Available":
                available += seats
        if available:
            numeric_id = re.match(r"\d+", instance_id)[0]
            # Official iframe documentation specifies the integer ID prefix.
            url = "https://book.youngvic.org/youngvic/website/ChooseSeats.aspx?" + urlencode({"EventInstanceId": numeric_id, "resize": "true"})
            candidates.append({"instance_id": instance_id, "key": f"{start.isoformat()}|{url}", "when": start.astimezone(LONDON).strftime("%Y-%m-%d %H:%M"), "url": url})
    if not total:
        raise MonitorError("No future public Eurotrash performances were returned")
    return {"total": total, "candidates": candidates}


def confirm_public_seats(candidate, status):
    """Exclude wheelchair seats and all eligibility/companion locks.

    'available' is documented as ordinary purchasable seats, excluding locks,
    other baskets, reservations and sold seats. Do not add wheelchairAvailable,
    specialAvailable, lockInfoAvailable or lockInfoSpecialAvailable.
    """
    if not isinstance(status, dict):
        raise MonitorError("Seat confirmation returned invalid data")
    available = count(status.get("available"))
    capacity = count(status.get("capacity"))
    if not capacity or available > capacity:
        raise MonitorError("Inconsistent seat availability")
    if not available:
        return None
    return dict(candidate, count=available, confirmed=True)


def observe(now, on_candidates=None):
    params = urlencode({"name": "Eurotrash", "instanceStart_from": now.astimezone(LONDON).date().isoformat(), "instanceStart_to": END.date().isoformat()})
    select_event(request_json(TICKETS + "/events?" + params))
    date_params = urlencode({"start_from": now.astimezone(LONDON).date().isoformat(), "start_to": END.date().isoformat()})
    base = TICKETS + "/events/" + EVENT_ID
    instances = request_json(base + "/instances?" + date_params)
    inventory = request_json(base + "/availability?" + date_params)
    result = parse_inventory(instances, inventory, now)
    if on_candidates is not None:
        on_candidates(result["candidates"])
    available = []
    for candidate in result["candidates"]:
        status = request_json(TICKETS + "/instances/" + candidate["instance_id"] + "/status?includeChildPlans=true")
        item = confirm_public_seats(candidate, status)
        if item:
            available.append(item)
    return {"total": result["total"], "available": available, "source": "official_spektrix_public_web_api"}


class GitHub:
    def __init__(self, state_path=STATE_PATH):
        self.state_path = state_path
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
            item = self.call("/contents/" + self.state_path)
        except HTTPError as exc:
            if exc.code == 404:
                return {}, None
            raise
        return json.loads(base64.b64decode(item["content"])), item["sha"]

    def save(self, state, sha):
        data = {"message": "Update monitor state [skip ci]", "content": base64.b64encode((json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()).decode()}
        if sha:
            data["sha"] = sha
        return self.call("/contents/" + self.state_path, "PUT", data)

    def notify(self, title, body, marker):
        # An alert may have been delivered immediately before a state-save
        # failure. Check the issue marker before creating a duplicate.
        for issue in self.call("/issues?state=all&per_page=100&sort=created&direction=desc"):
            if marker in (issue.get("body") or ""):
                return issue["html_url"]
        result = self.call("/issues", "POST", {"title": title, "body": f"@{self.owner}\n\n{body}\n\n<!-- {marker} -->"})
        if not result.get("id"):
            raise MonitorError("GitHub did not acknowledge the alert")
        return result["html_url"]


def alert_body(items, now):
    lines = ["Young Vic 官方售票服务已确认 Eurotrash 有普通公开可购座位。", "", f"核验时间：{now.astimezone(LONDON):%Y-%m-%d %H:%M:%S}（伦敦时间）", ""]
    for item in items:
        lines.append(f"- **{item['when']}（伦敦时间）**：核验时 {item['count']} 张普通公开座位；[打开官方购票页]({item['url']})")
    lines.extend(["", "票价未知，请在官方售票页核对。余票随时可能售出。监控只读取公开状态，不会替你订票。"])
    return "\n".join(lines)


def candidate_body(name, items, now):
    lines = [f"{name} 官方场次出现购票入口或可购信号。尚未完成可选座位核验，不能确认一定有票。", "", f"发现时间：{now.astimezone(LONDON):%Y-%m-%d %H:%M:%S}（伦敦时间）", ""]
    lines += [f"- **{item['when']}（伦敦时间）**：[立即打开官方购票页]({item['url']})" for item in items]
    lines += ["", "票价和实际余票待核实。确认有公开可选票后会另发确认通知。入口可能很快关闭，请自行查看；监控不会占座或购买。"]
    return "\n".join(lines)


def run(*, config=None, observer=None, github=None):
    config = config or {}
    name = config.get("name", "Young Vic《Eurotrash》")
    prefix = config.get("prefix", "eurotrash")
    show_url = config.get("url", SHOW)
    end = config.get("end", END)
    format_alert = config.get("format_alert", alert_body)
    now = datetime.now(timezone.utc)
    if now >= end:
        print(name + " has finished. No further ticket checks or alerts.")
        return
    gh = github() if github else GitHub()
    state, sha = gh.state()
    before = json.dumps(state, sort_keys=True)
    stamp = now.isoformat()
    notification_error = None
    state["last_attempt_at"] = stamp
    state["last_run_id"] = os.environ.get("GITHUB_RUN_ID")
    if config.get("scope") == "london_today_only":
        state.update(scope="london_today_only", scope_date=now.astimezone(LONDON).date().isoformat())

    def publish_candidates(candidates):
        # Authorized on 19 October: send the early signal before slow browser
        # confirmation, explicitly distinguish it from confirmed availability.
        state["last_source_read_at"] = stamp
        old = set(state.get("candidate_notified_keys", []))
        fresh = [item for item in candidates if item["key"] not in old]
        if fresh:
            episode = state.get("candidate_episode", 0) + 1
            fingerprint = hashlib.sha256(json.dumps([i["key"] for i in fresh], sort_keys=True).encode()).hexdigest()[:20]
            url = gh.notify("【购票入口变化，余票待核实】" + name, candidate_body(name, fresh, now), prefix + "-candidate-" + str(episode) + "-" + fingerprint)
            print("Early booking signal acknowledged:", url)
            state["candidate_episode"] = episode
        state["candidate_notified_keys"] = [item["key"] for item in candidates]
        state["current_candidate_count"] = len(candidates)
    if os.environ.get("TEST_NOTIFICATION", "").lower() == "true":
        marker = prefix + "-setup-test-" + os.environ.get("GITHUB_RUN_ID", stamp)
        url = gh.notify("【测试，不是放票】" + name + " 云端通知测试", "这是 GitHub 云端监控发出的连接测试。**这不代表现在有票，也不代表查票链路已经通过验证。**\n\n监控对象：" + name + "\n\n" + show_url + "\n\n若你收到这封邮件，邮件通知链路已连通。手机可开启 GitHub Mobile 的 Mentions 推送，或 Gmail 新邮件通知。", marker)
        print("Test notification created:", url)
    try:
        observation = (observer or observe)(now, on_candidates=publish_candidates)
        items = observation["available"]
        old_keys = set(state.get("notified_keys", []))
        fresh = [item for item in items if item["key"] not in old_keys]
        if fresh:
            fingerprint = hashlib.sha256(json.dumps([i["key"] for i in fresh], sort_keys=True).encode()).hexdigest()[:20]
            episode = str(state.get("episode", 0) + 1)
            url = gh.notify("【放票提醒】" + name + "有票了", format_alert(fresh, now), prefix + "-availability-" + episode + "-" + fingerprint)
            print("Availability notification acknowledged:", url)
            state["episode"] = int(episode)
        if state.get("failure_notice_sent"):
            gh.notify("【监控恢复】" + name + " 云端查票恢复", f"已重新读取 {name} 官方的 {observation['total']} 场未来演出。\n\n{show_url}", prefix + "-recovery-" + str(state.get("failure_episode", 0)))
        empty_status = "no_performances_today" if observation["total"] == 0 and config.get("empty_status") == "no_performances_today" else "sold_out"
        state.update(status="available" if items else empty_status, notified_keys=[item["key"] for item in items], consecutive_failures=0, failure_notice_sent=False, last_error=None, performance_count=observation["total"])
        if config.get("scope") == "london_today_only":
            state.pop("paused_at", None)
            state.pop("pause_reason", None)
        state["last_checked_at"] = datetime.now(timezone.utc).isoformat()
        state["check_count"] = state.get("check_count", 0) + 1
        print(json.dumps({"checked_at": stamp, "source": observation["source"], "performances": observation["total"], "confirmed_available_performances": len(items), "status": state["status"]}))
    except Exception as exc:
        count = state.get("consecutive_failures", 0) + 1
        state.update(status="unknown", consecutive_failures=count, last_error=str(exc)[:500])
        print("::warning::" + name + " availability could not be verified:", str(exc)[:250])
        if count >= 3 and not state.get("failure_notice_sent"):
            episode = state.get("failure_episode", 0) + 1
            try:
                gh.notify("【监控异常，不是放票】" + name + " 连续读取失败", f"已连续 {count} 次无法核实官方余票，不能确认售罄或有票。\n\n错误：{str(exc)[:300]}\n\n请查看 [本次云端运行]({os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{gh.repo}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')})。\n\n{show_url}", prefix + "-failure-" + str(episode))
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
    return state


if __name__ == "__main__":
    run()
