# Kalshi coherence & lead-lag scanner

A read-only scanner that watches [Kalshi](https://kalshi.com) prediction markets
for **internally inconsistent or stale prices** and posts a Discord alert when it
finds one — with a direct link to the market and the exact action to take. It runs
on a schedule for free via GitHub Actions; no server required.

It is **detection only** — it never places orders — and uses only public,
unauthenticated data, so there are no API keys to manage.

> **What to expect.** Liquid markets are mostly efficient, so real signals are
> rare and the scanner is quiet most of the time. That is the intended behavior:
> it is tuned to avoid false positives, not to find something every run. Hard
> locks are unambiguous; the softer signals (and complete-set candidates) still
> need a human to confirm fillable size and exhaustiveness before trading.

## Scanners

Four independent checks run every cycle (`run_scans.py`):

| # | Scanner | Type | What it flags |
|---|---|---|---|
| 1 | **Complete-set sweep** | hard arb* | Across *every* open mutually-exclusive event: buying YES on all outcomes costs < \$1 (or all NO costs < N−1) net of fees. Guarded against non-exhaustive "open field" events that produce fake arbs. |
| 2 | **Nesting locks** | hard arb | If event A contains event B then `P(A) ≥ P(B)`. A violating quote lets you buy `A-YES + B-NO` for < \$1 with a ≥ \$1 payout. Works across price *thresholds* (`{S>K_low} ⊇ {S>K_high}`) and *deadlines* (`before July ⊇ before June`). |
| 3 | **Within-ladder locks** | hard arb | The same bull-spread check inside one multi-strike ladder — its survival function must be monotone. |
| 4 | **Center-vs-spot lead-lag** | soft signal | Each daily price ladder should be centered on the live underlying. Using the ladder's own width and the live [Pyth](https://pyth.network) price, a whole-ladder shift away from spot is flagged — i.e. the ladder lagging a real move. |

\* The complete-set YES side depends on the event being *collectively exhaustive*,
which can't be proven from prices alone, so those alerts are labeled "verify
exhaustive" and are the one check that isn't a guaranteed lock.

A separate research tool, `tools/longshot_backtest.py`, tests the
favorite-longshot hypothesis (are longshots overpriced / favorites underpriced?)
against settled-market history.

## How it works

- **Data:** Kalshi's public market API + Pyth's public price feeds — read-only,
  no authentication.
- **Settlement references:** gold/silver ladders are compared against the *exact*
  Pyth feed Kalshi settles on; crypto (BTC/ETH/SOL/XRP/DOGE) uses Pyth as a close
  proxy for Kalshi's CF Benchmarks settlement.
- **Alerts:** a Discord webhook (the only secret). De-duplication state in
  `state/seen.json` prevents re-spamming a standing finding.
- **Output:** `results.json` always holds the latest scan, suitable for driving a
  status page.

## Repository layout

| path | role |
|---|---|
| `common.py` | shared helpers: HTTP, Pyth, Kalshi, survival-fit, fees, URLs |
| `scanners.py` | the four scanners → structured findings |
| `alerts.py` | Discord posting + de-duplication |
| `config.py` | underlyings, feeds, nesting families, thresholds |
| `run_scans.py` | one-shot run (the scheduled entry point) |
| `monitor.py` | optional continuous local loop |
| `.github/workflows/scan.yml` | the free scheduled runner |
| `docs/scheduling.md` | optional: force reliable 5-minute runs |
| `tools/discover_families.py` | find related-market families to scan |
| `tools/longshot_backtest.py` | favorite-longshot calibration study |

## Deploy your own

1. Fork or clone the repo and push it to your own GitHub account.
2. Create a Discord webhook (Server Settings → Integrations → Webhooks) and add it
   as a repository secret named `DISCORD_WEBHOOK_URL`
   (Settings → Secrets and variables → Actions → New repository secret).
3. The workflow in `.github/workflows/scan.yml` then runs automatically and
   commits `results.json` each cycle. Trigger it manually from the Actions tab to
   test immediately.

GitHub's built-in schedule is best-effort and often delayed; for reliable
5-minute cadence, see [`docs/scheduling.md`](docs/scheduling.md).

### Running locally

```bash
cp .env.example .env          # add your webhook to .env
export $(grep -v '^#' .env | xargs)
python3 run_scans.py          # one shot
DRY_RUN=1 python3 run_scans.py # print findings instead of posting
python3 monitor.py            # continuous loop
```

No third-party packages — Python 3.9+ standard library only.

## Configuration

Everything tunable lives in `config.py`:
- **`LADDER_VS_SPOT`** — underlyings to track, each with its Kalshi series and Pyth
  feed id.
- **`NESTING_SERIES`** — deadline/threshold ladder families (auto-detected;
  unknown or inactive series are skipped).
- **`THRESH`** — liquidity, edge, and exhaustiveness thresholds that keep alerts
  rare and trustworthy.

`tools/discover_families.py` lists Kalshi series that settle on the same
underlying across horizons — useful for finding new families to add.

## Security

- The scanners read only public endpoints, so the project ships with **no API
  keys**. The single secret is the Discord webhook, stored as a GitHub Actions
  secret (or a local `.env`, which is gitignored) — never in the code.
- The project is detection-only and never authenticates to a trading account. If
  you extend it to place orders, keep those credentials out of this repo and off
  shared infrastructure.

---

*Not financial advice. For research and educational use. Prediction-market trading
carries risk, and "edges" found by a model are frequently the model's own error —
verify independently before acting.*
