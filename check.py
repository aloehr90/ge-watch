"""Global Entry appointment checker — runs on GitHub Actions.

Looks up open slots at an enrollment center and sends a push notification to
your phone via ntfy.sh when a new one appears. Also tells you if the checker
itself has been failing, and sends a quiet weekly "still watching" message.

Settings come from environment variables (set as repository variables and
secrets in GitHub — see README.md); the defaults below watch Boise.
"""
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

# ---- Settings (override with environment variables) -------------------------
LOCATION_ID = os.environ.get("LOCATION_ID") or "12161"  # Boise Enrollment Center
LOCATION_NAME = os.environ.get("LOCATION_NAME") or "Boise"
# e.g. "2027-01-15" to only alert for slots on/before that date
BEFORE_DATE = os.environ.get("BEFORE_DATE") or ""
# Time zone of the center; the dashboard shows times in it
LOCATION_TZ = os.environ.get("LOCATION_TZ") or "America/Denver"
# Hours of the day (in that time zone) the schedule runs; shown on the dashboard
WATCH_START = os.environ.get("WATCH_START") or ""
WATCH_END = os.environ.get("WATCH_END") or ""
NTFY_TOPIC = os.environ.get("NTFY_TOPIC") or ""
NTFY_SERVER = (os.environ.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
TEST_MODE = os.environ.get("TEST_MODE", "false") == "true"
# ------------------------------------------------------------------------------

API = "https://ttp.cbp.dhs.gov/schedulerapi"
BOOKING_URL = "https://ttp.cbp.dhs.gov/"
STATE_FILE = "state.json"
HISTORY_FILE = "history.jsonl"               # one line per slot opening or closing
HISTORY_MAX_LINES = 5000
SLOT_LIMIT = 10                              # how many upcoming slots to look at
SLOTS_IN_MESSAGE = 5                         # how many of them to list in the alert
FETCH_ATTEMPTS = 3                           # tries per run before giving up
FAILURE_ALERT_AFTER = timedelta(minutes=30)  # how long checks fail before you're told
HEARTBEAT_EVERY = timedelta(days=7)


def now():
    return datetime.now(timezone.utc)


def fetch_slots():
    """Return the start times of the soonest open slots, e.g. "2026-12-24T07:50"."""
    url = (f"{API}/slots?orderBy=soonest&limit={SLOT_LIMIT}&minimum=1"
           f"&locationId={LOCATION_ID}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ge-watch"})
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                slots = sorted(s["startTimestamp"] for s in json.load(r))
            for s in slots:
                datetime.fromisoformat(s)  # fail here if the format ever changes
            return slots
        except Exception as e:  # network error, bad JSON, unexpected shape
            print(f"Attempt {attempt}/{FETCH_ATTEMPTS} failed: {e!r}")
            if attempt == FETCH_ATTEMPTS:
                raise
            time.sleep(10 * attempt)


def notify(title, message, priority="high", tags="airplane"):
    req = urllib.request.Request(
        f"{NTFY_SERVER}/{NTFY_TOPIC}",
        data=message.encode(),
        headers={"Title": title, "Priority": priority, "Tags": tags, "Click": BOOKING_URL},
    )
    urllib.request.urlopen(req, timeout=30)
    print(f"Notification sent: {title} | {message}")


def pretty(slot):
    """ "2026-12-24T07:50" -> "Thu Dec 24, 7:50 AM" (the center's local time)."""
    d = datetime.fromisoformat(slot)
    return f"{d:%a %b} {d.day}, {d.hour % 12 or 12}:{d:%M %p}"


def opening_message(slots):
    count = f"{len(slots)}+" if len(slots) >= SLOT_LIMIT else str(len(slots))
    if len(slots) == 1:
        return f"Appointment available {pretty(slots[0])}"
    lines = [f"{count} openings, soonest {pretty(slots[0])}"]
    lines += [f"Also: {pretty(s)}" for s in slots[1:SLOTS_IN_MESSAGE]]
    return "\n".join(lines)


def load_state():
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
        return state if isinstance(state, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
        f.write("\n")


def record_history(opened, closed):
    """Append what changed since the last check; the dashboard charts this."""
    if not (opened or closed):
        return
    at = now().isoformat(timespec="seconds")
    try:
        with open(HISTORY_FILE) as f:
            lines = f.read().splitlines()
    except OSError:
        lines = []
    lines += [json.dumps({"at": at, "event": "closed", "slot": s}) for s in closed]
    lines += [json.dumps({"at": at, "event": "opened", "slot": s}) for s in opened]
    with open(HISTORY_FILE, "w") as f:
        f.write("\n".join(lines[-HISTORY_MAX_LINES:]) + "\n")


def record_failure(state, error):
    """Remember when checks started failing; alert once if it goes on too long."""
    since = state.setdefault("failing_since", now().isoformat(timespec="seconds"))
    too_long = now() - datetime.fromisoformat(since) >= FAILURE_ALERT_AFTER
    if too_long and not state.get("failure_alerted"):
        try:
            notify(f"Global Entry: {LOCATION_NAME} checker is failing",
                   f"Checks have failed since {since[:16].replace('T', ' ')} UTC.\n"
                   f"Last error: {error!r}", priority="default", tags="warning")
            state["failure_alerted"] = True
        except Exception as e:
            print(f"Could not send failure alert: {e!r}")


def main():
    if not NTFY_TOPIC:
        sys.exit("NTFY_TOPIC secret is not set (Settings > Secrets and variables > Actions).")

    state = load_state()

    if TEST_MODE:
        notify("Global Entry: test", "If you can read this, notifications work!")

    try:
        slots = fetch_slots()
    except Exception as e:
        record_failure(state, e)
        save_state(state)
        sys.exit(f"Could not check appointments: {e!r}")

    if state.pop("failure_alerted", False):
        notify(f"Global Entry: {LOCATION_NAME} checker recovered",
               "Checks are working again.", priority="default", tags="white_check_mark")
    state.pop("failing_since", None)
    state.pop("last_alert", None)  # field from the first version of this script

    if BEFORE_DATE:
        slots = [s for s in slots if s[:10] <= BEFORE_DATE]

    # Alert only for slots we haven't already told you about. When the list was
    # full last time, a later slot scrolling into view isn't news — an earlier one is.
    seen = state.get("open_slots", [])
    new = [s for s in slots if s not in seen]
    if len(seen) >= SLOT_LIMIT:
        new = [s for s in new if s < max(seen)]

    if not slots:
        print("No openings" + (f" on or before {BEFORE_DATE}." if BEFORE_DATE else "."))
    elif new:
        notify(f"Global Entry: {LOCATION_NAME} opening", opening_message(slots))
    else:
        print(f"Still open: {', '.join(slots)} (already notified).")
    record_history(opened=[s for s in slots if s not in seen],
                   closed=[s for s in seen if s not in slots])
    state["open_slots"] = slots

    # Settings the dashboard needs in order to describe what is being watched.
    state["location"] = {"id": LOCATION_ID, "name": LOCATION_NAME, "timezone": LOCATION_TZ}
    if WATCH_START and WATCH_END:
        state["watch_hours"] = [int(WATCH_START), int(WATCH_END)]
    if BEFORE_DATE:
        state["before_date"] = BEFORE_DATE
    else:
        state.pop("before_date", None)

    # Weekly heartbeat: shows the watcher is alive, and the resulting commit keeps
    # GitHub from disabling the schedule after 60 days without repository activity.
    last = state.get("heartbeat")
    if not last:
        state["heartbeat"] = now().isoformat(timespec="seconds")
    elif now() - datetime.fromisoformat(last) >= HEARTBEAT_EVERY:
        state["heartbeat"] = now().isoformat(timespec="seconds")
        try:
            notify(f"Global Entry: still watching {LOCATION_NAME}",
                   "Weekly check-in: the watcher is running.", priority="min", tags="eyes")
        except Exception as e:
            print(f"Could not send heartbeat: {e!r}")

    save_state(state)


if __name__ == "__main__":
    main()
