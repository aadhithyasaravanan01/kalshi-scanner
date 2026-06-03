#!/usr/bin/env python3
"""First-pass favorite-longshot calibration test on Kalshi.

Hypothesis (favorite-longshot bias): longshots (low YES price) are OVERpriced
-> they resolve YES LESS often than priced; favorites (high YES price) are
UNDERpriced -> they resolve YES MORE often than priced.

Method: sample SETTLED markets from liquid daily ladders (their strikes span the
whole probability range). For each, take the YES mid-price at ~50% of the
market's life (a pre-resolution belief, before prices converge to 0/1), and
record (price, resolved_yes). Bucket by price; compare mean price to empirical
YES rate. A well-calibrated market sits on the diagonal; the bias shows as
empirical < price at the low end and empirical > price at the high end.

Caveats: noisy first pass. Lead time = 50% of life (arbitrary). Liquidity filter
biases toward traded strikes. Not a clean fixed-horizon study. Directional only.
"""
import json, urllib.request, calendar, datetime, sys

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "longshot-backtest/1.0"}
SERIES = ["KXBTCD", "KXETHD", "KXSOLD", "KXXRPD", "KXDOGED",
          "KXHIGHNY", "KXHIGHTHOU", "KXHIGHMIA", "KXHIGHTPHX"]
MAX_PER_SERIES = 60
MIN_LIFE_VOL = 20.0           # require some real trading for a trustworthy price
LIFE_FRACTION = 0.5           # snapshot price at this fraction through the market


def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read())


def ts(s):
    return calendar.timegm(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timetuple())


def snapshot_price(series, m):
    """YES mid-price at ~LIFE_FRACTION through the market's life, or None."""
    try:
        o, c = ts(m["open_time"]), ts(m["close_time"])
    except Exception:
        return None
    if c - o < 120:
        return None
    target = o + LIFE_FRACTION * (c - o)
    url = (f"{KALSHI}/series/{series}/markets/{m['ticker']}/candlesticks"
           f"?start_ts={o}&end_ts={c}&period_interval=60")
    try:
        cs = get(url).get("candlesticks", [])
    except Exception:
        return None
    if not cs:
        return None
    life_vol = sum(float(x.get("volume_fp") or 0) for x in cs)
    if life_vol < MIN_LIFE_VOL:
        return None
    best = min(cs, key=lambda x: abs(float(x.get("end_period_ts", 0)) - target))
    try:
        a = float(best["yes_ask"]["close_dollars"]); b = float(best["yes_bid"]["close_dollars"])
    except (KeyError, TypeError, ValueError):
        return None
    if a <= 0 and b <= 0:
        return None
    return (a + b) / 2.0


def main():
    pts = []   # (price, resolved_yes)
    for s in SERIES:
        try:
            ms = get(f"{KALSHI}/markets?series_ticker={s}&status=settled&limit={MAX_PER_SERIES}").get("markets", [])
        except Exception:
            continue
        kept = 0
        for m in ms:
            r = m.get("result")
            if r not in ("yes", "no"):
                continue
            p = snapshot_price(s, m)
            if p is None:
                continue
            pts.append((p, 1 if r == "yes" else 0))
            kept += 1
        print(f"  {s}: {kept} usable settled markets", file=sys.stderr)

    print(f"\nSample: {len(pts)} (price, outcome) points\n")
    if len(pts) < 30:
        print("Too few points for a read."); return

    bins = [(i / 10, (i + 1) / 10) for i in range(10)]
    print(f"{'price bin':>11} {'n':>5} {'mean price':>11} {'emp P(yes)':>11} {'emp-price':>10}")
    rows = []
    for lo, hi in bins:
        grp = [(p, y) for p, y in pts if lo <= p < hi or (hi == 1.0 and p == 1.0)]
        if not grp:
            continue
        mp = sum(p for p, _ in grp) / len(grp)
        emp = sum(y for _, y in grp) / len(grp)
        rows.append((lo, hi, len(grp), mp, emp))
        flag = ""
        if len(grp) >= 8:
            if emp < mp - 0.03:
                flag = "  <- resolves LESS than priced"
            elif emp > mp + 0.03:
                flag = "  <- resolves MORE than priced"
        print(f"{lo:.1f}-{hi:.1f}  {len(grp):>5} {mp:>11.3f} {emp:>11.3f} {emp-mp:>+10.3f}{flag}")

    low = [r for r in rows if r[3] < 0.25 and r[2] >= 8]
    high = [r for r in rows if r[3] > 0.75 and r[2] >= 8]
    print("\nVerdict (favorite-longshot bias = longshots resolve LESS, favorites MORE):")
    if low:
        d = sum((r[4] - r[3]) for r in low) / len(low)
        print(f"  longshots (price<0.25): empirical-price avg = {d:+.3f} "
              f"({'OVERpriced (bias present)' if d < -0.02 else 'roughly calibrated'})")
    if high:
        d = sum((r[4] - r[3]) for r in high) / len(high)
        print(f"  favorites (price>0.75): empirical-price avg = {d:+.3f} "
              f"({'UNDERpriced (bias present)' if d > 0.02 else 'roughly calibrated'})")


if __name__ == "__main__":
    main()
