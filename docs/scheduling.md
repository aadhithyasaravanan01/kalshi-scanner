# Reliable scheduling (force runs every 5 minutes)

GitHub's built-in `schedule:` trigger is best-effort — it's often delayed 5–20 min
or skipped under load. To get **reliable** 5-minute runs, have a free external cron
service call GitHub's `workflow_dispatch` API on a fixed schedule. The `schedule:`
block stays as a fallback.

## 1. Create a fine-grained GitHub token (least privilege)

GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained
tokens → Generate new token**:
- **Repository access:** Only select repositories → `kalshi-scanner`
- **Permissions:** Repository permissions → **Actions: Read and write** (nothing else)
- **Expiration:** your choice (you'll rotate it)
- Generate, copy the token (`github_pat_…`). Treat it like a password.

This token can *only* trigger Actions on this one repo — minimal blast radius.

## 2. Create the cron job at cron-job.org (free)

Sign up at https://cron-job.org → **Create cronjob**:
- **URL:**
  ```
  https://api.github.com/repos/aadhithyasaravanan01/kalshi-scanner/actions/workflows/scan.yml/dispatches
  ```
- **Schedule:** every 5 minutes (`*/5`).
- **Request method:** `POST`
- **Request headers:**
  ```
  Authorization: Bearer github_pat_YOUR_TOKEN_HERE
  Accept: application/vnd.github+json
  X-GitHub-Api-Version: 2022-11-28
  Content-Type: application/json
  ```
- **Request body:**
  ```json
  {"ref":"main"}
  ```
- Save. (A successful dispatch returns HTTP **204**.)

That's it — every 5 minutes cron-job.org pokes GitHub, which runs `scan.yml`
on `main` reliably. You'll see the runs appear in the **Actions** tab.

## Verify

- cron-job.org's execution log should show **204** responses.
- The repo's **Actions** tab shows a run every ~5 min with source "workflow_dispatch".
- `results.json` commits should appear on a steady ~5-min cadence.

## Notes
- The token lives only in cron-job.org's request config, never in this repo.
- Rotate the token periodically (regenerate, update the cron job's header).
- Alternative for rock-solid cadence: a $4/mo VPS running `python3 monitor.py`.
