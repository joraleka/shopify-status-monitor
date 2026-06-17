# Shopify Status → Slack

Posts Shopify **platform** status changes (incidents, updates, recovery) from
[shopifystatus.com](https://www.shopifystatus.com) into the
`#joraleka-shopify-status` Slack channel.

A scheduled GitHub Action polls Shopify's status, compares it to the last known
state, and posts to Slack **only when something changes** — so the channel stays
quiet until there's an actual incident.

---

## How it works

1. **Primary source:** the Atlassian Statuspage JSON API (`/api/v2/summary.json`).
   This gives the overall status indicator plus all *unresolved* incidents with
   their latest update.
2. **Fallback:** if Shopify has that endpoint disabled, the script scrapes the
   public HTML page for the **overall** status only (operational ⟷ affected) and
   notifies on that transition. Per-incident detail is only available on the API
   path.
3. **State** is kept in `state.json`; the workflow commits it back to the repo
   when (and only when) it changes. No external database needed.

Message types posted to Slack:
- 🔴/🟡 **New incident** — name, impact, latest update, link
- 🟠 **Update** — status change or new update on an open incident
- ✅ **Resolved** — incident cleared
- A one-time **baseline** message on the very first run

---

## Setup (3 steps)

1. **Push this repo to GitHub** (a new repo, e.g. `joraleka/shopify-status-monitor`).
   See the quota note below for the public-vs-private choice.

2. **Create the Slack incoming webhook** and store it as a secret:
   - Slack: create an app at <https://api.slack.com/apps> → *Incoming Webhooks* →
     enable → *Add New Webhook to Workspace* → pick `#joraleka-shopify-status`.
     This counts as **1 of the 10 free-plan app slots.**
   - GitHub: repo → **Settings → Secrets and variables → Actions → New repository
     secret** → name it `SLACK_WEBHOOK_URL`, paste the webhook URL.
   - **Never** put the webhook in the code or in `state.json`. It lives only in
     the GitHub secret; the script reads it from the environment.

3. **Enable Actions and test:** repo → **Actions** tab → enable workflows →
   open *Shopify Status → Slack* → **Run workflow** (manual dispatch). You should
   see the baseline message land in Slack within a few seconds.

After that, the cron takes over.

---

## ⚠️ Free-tier quota note (read before choosing private)

GitHub Actions minutes are **free and unlimited on public repos**, but a private
repo on the Free plan gets **2,000 minutes/month**. Each run is billed as at
least 1 minute. At `*/5` that's ~8,640 runs/month → **well over the private
free quota.** Pick one:

- **Public repo (recommended, simplest):** unlimited minutes, keep `*/5`. This is
  safe here — the only secret (the webhook) stays encrypted in GitHub secrets and
  is never exposed by a public repo. The code and incident history are not
  sensitive.
- **Private repo, less frequent:** change the cron to `*/30` (~1,440 min/month,
  comfortably under 2,000). Trade-off: up to ~30 min of latency on an incident.
- **Private + frequent + free:** use a **Cloudflare Worker Cron Trigger** instead
  (free, 1-minute granularity, state via Workers KV). Same logic, different host —
  ask and we'll port it.

---

## Tuning

- **Frequency:** edit the `cron` line in
  `.github/workflows/shopify-status.yml`.
- **Message format / emojis:** edit `INDICATOR_EMOJI` and the message strings in
  `check_status.py`.

---

## Scope & roadmap

- **v1 (this repo):** global Shopify platform status (shopifystatus.com), no auth.
- **v2 (optional):** store-specific status from
  [my.shopifystatus.com](https://my.shopifystatus.com) — requires a logged-in
  Shopify session, so it needs authenticated scraping.
- **Storefront uptime** (is joraleka.com reachable for customers): a different
  tool — UptimeRobot or similar, which has a native free Slack integration.

---

## Suggested channel topic

> Automated Shopify platform status alerts (incidents, maintenance, recovery)
> from shopifystatus.com. Quiet unless there's an issue. Source:
> https://www.shopifystatus.com
