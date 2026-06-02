# Kalshi coherence & lead-lag scanner

A read-only detector for **internally inconsistent or stale prices** on
[Kalshi](https://kalshi.com) prediction markets. It runs on a schedule (free,
via GitHub Actions — no server needed) and posts a Discord alert **only** when it
finds a trustworthy signal, with a direct link to the market and the exact action
to take.

> **Honest expectations.** Liquid markets are mostly efficient — these signals
> are *rare*. This is a disciplined detector that stays quiet, not a money
> printer. Every alert still needs a human to verify fillable size and fees
> before trading. Detection only: it never places orders.

## What it looks for

1. **Nesting locks (hard arbitrage).** If event A contains event B, then
   `P(A) ≥ P(B)`. When the quotes violate that, buying `A-YES + B-NO` pays ≥ \$1
   for < \$1 — guaranteed. Works across price *thresholds* (`{S>K_low} ⊇ {S>K_high}`)
   and *deadlines* (`{cross before July} ⊇ {cross before June}`).
2. **Within-ladder locks.** The same bull-spread check inside a single multi-strike
   ladder (the survival function must be monotone).
3. **Center-vs-spot divergence (lead-lag).** Each daily ladder should be centered
   on the live underlying. Using each ladder's *own* width (not an assumed model),
   a strike that disagrees with the live [Pyth](https://pyth.network) price — the
   exact reference Kalshi settles on — is flagged. Fires only when a ladder lags a
   real move.

## How it works

- **Data:** Kalshi's public market API + Pyth's public price feeds. **No API keys,
  no authentication, read-only.** The only secret is your Discord webhook.
- **Settlement-exact:** gold/silver/BTC/ETH ladders are compared against the *same*
  Pyth feed Kalshi settles on, so a gap is a real lag, not a proxy mismatch.

## Files

| file | role |
|---|---|
| `common.py` | shared helpers: HTTP, Pyth, Kalshi, survival-fit, URL builder |
| `scanners.py` | the scan functions (locks + center divergence) → findings |
| `alerts.py` | Discord posting + de-duplication state |
| `config.py` | what to scan (underlyings, feeds, nesting families, thresholds) |
| `run_scans.py` | one-shot run (the GitHub Actions entry point) |
| `monitor.py` | optional continuous local loop |
| `.github/workflows/scan.yml` | the free scheduled runner |
| `tools/discover_families.py` | find new related-market families to add to config |

## Setup

### Run hands-off on GitHub Actions (recommended, free)
1. Push this repo to GitHub.
2. Add the webhook as a secret: **Settings → Secrets and variables → Actions →
   New repository secret**, name `DISCORD_WEBHOOK_URL`, value = your Discord webhook.
3. That's it — `scan.yml` runs every ~15 min and commits `results.json`.

### Run locally
```bash
cp .env.example .env          # then paste your webhook into .env
export $(grep -v '^#' .env | xargs)
python run_scans.py           # one shot
DRY_RUN=1 python run_scans.py # print instead of posting
python monitor.py             # continuous loop
```

## Security

This repo is safe to make public: it contains **no keys** (all data sources are
public/read-only). The Discord webhook is the only secret and lives in
GitHub Actions secrets / your local `.env` (gitignored) — never in the code.
If you ever add order *execution*, keep those keys out of this repo and off
shared infra.

## Extending

Add related-market families to `config.py`. Use `tools/discover_families.py` to
find series that settle on the same underlying across horizons.

---
*Not financial advice. For research and educational use.*
