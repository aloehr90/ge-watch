# ge-watch

Watches a Global Entry enrollment center (Boise by default) for open interview
slots and sends a push notification to your phone when a new one appears.

It runs on GitHub Actions every 5 minutes between 5 AM and 11 PM Mountain
time, so there is nothing to host. Manual runs work at any hour. To change the
hours, edit the schedule and the first step in `.github/workflows/check.yml`.

## Setup

1. Install the [ntfy](https://ntfy.sh) app on your phone and subscribe to a
   topic with a long, hard-to-guess name. Anyone who knows the name can read
   and send to it, so treat it like a password.
2. In this repository, go to **Settings > Secrets and variables > Actions** and
   add a secret named `NTFY_TOPIC` with that topic name.
3. Go to **Actions > Check Global Entry appointments > Run workflow**, tick
   **Send a test notification**, and run it. Your phone should buzz.

## Dashboard

A read-only status page lives in `docs/index.html`. It shows current openings,
whether the watcher is running, and charts of when openings have appeared.

To publish it, go to **Settings > Pages**, choose **Deploy from a branch**,
select `main` and the `/docs` folder, and save. After a minute or two it is
served at `https://<your-username>.github.io/<repository-name>/`.

The page is public, like the repository. It reads `state.json`, `history.jsonl`
and the public run history when you open it, so it can lag by a few minutes.

To preview it locally, run this from the repository root and open
<http://localhost:8000/docs/>:

```bash
python3 -m http.server
```

## Settings

Optional. Add these under **Settings > Secrets and variables > Actions >
Variables**; anything left unset uses the default.

| Variable        | Default           | Meaning                                                  |
| --------------- | ----------------- | -------------------------------------------------------- |
| `LOCATION_ID`   | `12161`           | Enrollment center to watch (12161 is Boise).             |
| `LOCATION_NAME` | `Boise`           | Name used in the notifications.                          |
| `BEFORE_DATE`   | none              | Only alert for slots on or before this date (`2027-01-15`). |
| `LOCATION_TZ`   | `America/Denver`  | Time zone of the center, used for watch hours and the dashboard. |
| `NTFY_SERVER`   | `https://ntfy.sh` | Use a self-hosted ntfy server instead.                   |

Location IDs are listed at
<https://ttp.cbp.dhs.gov/schedulerapi/locations/?temporary=false&inviteOnly=false&operational=true&serviceName=Global%20Entry>.

## What you will receive

- **Opening** (high priority): sent when a slot appears that you have not
  already been told about. It lists the soonest few times, in the center's
  local time. Tap it to open the Trusted Traveler site and book.
- **Checker is failing**: sent once if checks have been failing for 30 minutes,
  followed by a **recovered** message when they work again.
- **Still watching** (silent): a weekly check-in confirming the watcher is alive.

## How it works

`check.py` asks the CBP scheduler API for the soonest open slots and compares
them with the ones recorded in `state.json`. The workflow commits `state.json`
back to the repository whenever it changes, which is how the watcher remembers
what it has already told you. Each slot that opens or closes is also appended
to `history.jsonl`, which feeds the dashboard's charts. The weekly heartbeat also updates that file; the
commit keeps GitHub from disabling the schedule, which it does to repositories
with no activity for 60 days.

To run it locally:

```bash
NTFY_TOPIC=your-topic python3 check.py
```
