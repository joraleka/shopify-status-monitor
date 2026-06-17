#!/usr/bin/env python3
"""
Poll Shopify's public status page and post changes to a Slack channel via an
incoming webhook.

Primary source : the Atlassian Statuspage JSON API (summary.json).
Fallback       : if Shopify has that endpoint disabled, scrape the public HTML
                 page for the overall status only (incident-level detail is not
                 reliable from the HTML, so the fallback notifies on the overall
                 operational <-> affected transition).

State is persisted in state.json so we only notify on *actual* changes. The
GitHub Actions workflow commits state.json back to the repo when (and only
when) it changes.

Required environment variable:
    SLACK_WEBHOOK_URL   the Slack incoming-webhook URL (stored as a repo secret)
"""

import json
import os
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

STATUS_HOME = "https://www.shopifystatus.com"
SUMMARY_API = f"{STATUS_HOME}/api/v2/summary.json"
STATE_FILE = Path("state.json")
WEBHOOK = os.environ.get("SLACK_WEBHOOK_URL")
UA = {"User-Agent": "joraleka-shopify-status-monitor/1.0 (+github-actions)"}
TIMEOUT = 20

INDICATOR_EMOJI = {
    "none": "✅",
    "minor": "🟡",
    "major": "🟠",
    "critical": "🔴",
    "maintenance": "🛠️",
}


# --------------------------------------------------------------------------- #
# Fetching
# --------------------------------------------------------------------------- #
def fetch_state():
    """Return current status as a normalized dict.

    {
      "source": "api" | "scrape",
      "indicator": "none|minor|major|critical|maintenance",
      "description": "All Systems Operational",
      "incidents": {
          "<id>": {"name", "status", "impact", "url",
                   "last_update", "updated_at"},
          ...
      }
    }
    """
    try:
        return _fetch_via_api()
    except Exception as exc:  # noqa: BLE001 - any failure should fall back
        print(f"[warn] API path failed ({exc!r}); falling back to HTML scrape")
        return _fetch_via_scrape()


def _fetch_via_api():
    r = requests.get(SUMMARY_API, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    status = data.get("status", {}) or {}
    incidents = {}
    # summary.json only lists *unresolved* incidents - exactly what we want.
    for inc in data.get("incidents", []) or []:
        updates = inc.get("incident_updates") or []
        body = updates[0].get("body", "").strip() if updates else ""
        incidents[inc["id"]] = {
            "name": (inc.get("name") or "").strip(),
            "status": inc.get("status", ""),
            "impact": inc.get("impact", "none"),
            "url": inc.get("shortlink") or f"{STATUS_HOME}/incidents/{inc['id']}",
            "last_update": body,
            "updated_at": inc.get("updated_at", ""),
        }
    return {
        "source": "api",
        "indicator": status.get("indicator", "none"),
        "description": (status.get("description") or "").strip(),
        "incidents": incidents,
    }


def _fetch_via_scrape():
    r = requests.get(STATUS_HOME, headers=UA, timeout=TIMEOUT)
    r.raise_for_status()
    text = r.text
    # The "All Systems Operational" banner is the one reliable signal in the
    # rendered HTML. Per-incident parsing from the home page is intentionally
    # avoided because past (resolved) incidents are also linked there.
    operational = "all systems operational" in text.lower()
    BeautifulSoup(text, "html.parser")  # validate it parses; no extraction
    return {
        "source": "scrape",
        "indicator": "none" if operational else "major",
        "description": "All Systems Operational" if operational
                       else "One or more systems affected",
        "incidents": {},
    }


# --------------------------------------------------------------------------- #
# Diffing
# --------------------------------------------------------------------------- #
def diff_and_notify(old, new):
    """Return the list of Slack messages to post for this transition."""
    if new.get("source") == "api" and old.get("source") == "api":
        return _incident_diffs(old, new)
    # Sources differ or we're on the HTML fallback -> overall-level only.
    return _overall_diff(old, new)


def _incident_diffs(old, new):
    msgs = []
    old_incs, new_incs = old.get("incidents", {}), new.get("incidents", {})

    for inc_id, inc in new_incs.items():
        prev = old_incs.get(inc_id)
        if prev is None:
            emoji = "🔴" if inc.get("impact") in ("critical", "major") else "🟡"
            line = f"{emoji} *New incident — {inc['name']}*"
            if inc.get("impact") not in ("", "none", "unknown"):
                line += f"  _(impact: {inc['impact']})_"
            if inc.get("last_update"):
                line += f"\n{_trim(inc['last_update'])}"
            line += f"\n<{inc['url']}|Open incident>"
            msgs.append(line)
        elif (prev.get("status") != inc.get("status")) or \
             (prev.get("updated_at") != inc.get("updated_at")):
            line = f"🟠 *Update — {inc['name']}* → *{inc.get('status', '')}*"
            if inc.get("last_update"):
                line += f"\n{_trim(inc['last_update'])}"
            line += f"\n<{inc['url']}|Open incident>"
            msgs.append(line)

    for inc_id, inc in old_incs.items():
        if inc_id not in new_incs:
            msgs.append(
                f"✅ *Resolved — {inc['name']}*"
                f"\n<{inc.get('url', STATUS_HOME)}|Incident page>"
            )
    return msgs


def _overall_diff(old, new):
    if old.get("indicator", "none") == new.get("indicator", "none"):
        return []
    ind = new.get("indicator", "none")
    emoji = INDICATOR_EMOJI.get(ind, "ℹ️")
    if ind == "none":
        return [f"{emoji} *All Shopify systems operational again.*"
                f"\n<{STATUS_HOME}|shopifystatus.com>"]
    return [f"{emoji} *Shopify is reporting an issue* — "
            f"{new.get('description') or ind}."
            f"\nDetails: <{STATUS_HOME}|shopifystatus.com>"]


def _trim(text, limit=400):
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --------------------------------------------------------------------------- #
# Slack
# --------------------------------------------------------------------------- #
def post(text):
    if not WEBHOOK:
        print("[error] SLACK_WEBHOOK_URL is not set")
        sys.exit(1)
    resp = requests.post(WEBHOOK, json={"text": text}, timeout=TIMEOUT)
    if resp.status_code != 200:
        print(f"[error] Slack webhook returned {resp.status_code}: {resp.text}")
        sys.exit(1)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    new = fetch_state()

    if not STATE_FILE.exists():
        # First run: announce the baseline, do not replay incident history.
        emoji = INDICATOR_EMOJI.get(new["indicator"], "ℹ️")
        post(
            f"{emoji} *Shopify status monitoring is live.*\n"
            f"Current status: *{new['description'] or new['indicator']}*\n"
            f"<{STATUS_HOME}|shopifystatus.com>"
        )
        STATE_FILE.write_text(json.dumps(new, indent=2, ensure_ascii=False))
        print("[ok] baseline saved")
        return

    old = json.loads(STATE_FILE.read_text())
    messages = diff_and_notify(old, new)
    for msg in messages:
        post(msg)
        print(f"[ok] posted: {msg.splitlines()[0]}")

    STATE_FILE.write_text(json.dumps(new, indent=2, ensure_ascii=False))
    print(f"[ok] state updated ({len(messages)} change(s))")


if __name__ == "__main__":
    main()
