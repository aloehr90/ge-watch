"""Global Entry appointment checker — runs on GitHub Actions.

Looks up the soonest open slot at an enrollment center and sends a push
notification to your phone via ntfy.sh when one appears.
"""
import json
import os
import sys
import urllib.request

# ---- Settings (edit these) -------------------------------------------------
LOCATION_ID = 12161  # Boise Enrollment Center, 4655 S Enterprise St
BEFORE_DATE = ""  # e.g. "2027-01-15" to only alert for slots on/before that date
# ----------------------------------------------------------------------------

API = "https://ttp.cbp.dhs.gov/schedulerapi"
STATE_FILE = "state.json"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
TEST_MODE = os.environ.get("TEST_MODE", "false") == "true"


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ge-watch"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def notify(title, message):
    if not NTFY_TOPIC:
        sys.exit("NTFY_TOPIC secret is not set (Settings > Secrets and variables > Actions).")
    req = urllib.request.Request(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode(),
        headers={
            "Title": title,
            "Priority": "high",
            "Tags": "airplane",
            "Click": "https://ttp.cbp.dhs.gov/",
        },
    )
    urllib.request.urlopen(req, timeout=30)
    print("Notification sent:", message)


def main():
    state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            state = json.load(f)

    if TEST_MODE:
        notify("Global Entry: test", "If you can read this, notifications work!")

    # Ask for the soonest open slot
    slots = get_json(f"{API}/slots?orderBy=soonest&limit=1&minimum=1"
                     f"&locationId={LOCATION_ID}")
    soonest = slots[0]["startTimestamp"] if slots else ""

    if not soonest:
        print("No openings.")
        state["last_alert"] = ""
    elif BEFORE_DATE and soonest[:10] > BEFORE_DATE:
        print(f"Soonest is {soonest}, after {BEFORE_DATE} — ignoring.")
    elif soonest == state.get("last_alert"):
        print(f"Still open: {soonest} (already notified).")
    else:
        notify("Global Entry: Boise opening", f"Appointment available {soonest.replace('T', ' at ')}")
        state["last_alert"] = soonest

    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


if __name__ == "__main__":
    main()
