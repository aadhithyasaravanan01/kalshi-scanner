#!/usr/bin/env python3
"""Favorite-longshot calibration test on Kalshi — hardened.

Hypothesis: longshots (low YES price) are OVERpriced (resolve YES less than
priced) and favorites (high YES price) are UNDERpriced (resolve YES more).
Sub-hypothesis: the bias is stronger in LOW/MID-volume SPORTS (retail/emotional
betting, thinner bot arbitrage) than in weather.

Method: for each settled market, take the "early line" = YES mid-price at the
first candle where cumulative volume crosses EARLY_VOL (a pre/early-event belief,
before prices converge to 0/1). Record (price, resolved_yes, volume, category).
Then: calibration by price decile, BOTH tails, volume-tier segmentation, and
fee-adjusted EV for fade-longshot / back-favorite strategies.

Caveats: 'early line' is a proxy (markets open at different leads); low-volume
prices are noisy; EV uses mid prices so real spread eats some edge. Directional.
"""
import json, urllib.request, calendar, datetime, sys

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "longshot-backtest/2.0"}

CATEGORIES = {
    "sports": ["KXNBAGAME", "KXMLBGAME", "KXNHLGAME", "KXATPMATCH",
               "KXBRASILEIROGAME", "KXBELGIANPLGAME", "KXALEAGUEGAME",
               "KXACBGAME", "KXBSLGAME", "KXBOXINGFIGHT"],
    "weather": ["KXHIGHNY", "KXHIGHTHOU", "KXHIGHMIA", "KXHIGHTPHX"],
}
MAX_PER_SERIES = 70
EARLY_VOL = 10.0          # contracts of cumulative volume to define the "line"


def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read())


def ts(s):
    return calendar.timegm(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timetuple())


def fee(p):
    return 0.07 * p * (1.0 - p)


def early_line(series, m):
    """(yes_mid at first candle reaching EARLY_VOL cum-volume, total_volume)."""
    try:
        o, c = ts(m["open_time"]), ts(m["close_time"])
    except Exception:
        return None
    if c - o < 120:
        return None
    url = (f"{KALSHI}/series/{series}/markets/{m['ticker']}/candlesticks"
           f"?start_ts={o}&end_ts={c}&period_interval=60")
    try:
        cs = get(url).get("candlesticks", [])
    except Exception:
        return None
    if not cs:
        return None
    total = sum(float(x.get("volume_fp") or 0) for x in cs)
    if total < EARLY_VOL:
        return None
    cum = 0.0
    for x in cs:
        cum += float(x.get("volume_fp") or 0)
        if cum >= EARLY_VOL:
            try:
                a = float(x["yes_ask"]["close_dollars"]); b = float(x["yes_bid"]["close_dollars"])
            except (KeyError, TypeError, ValueError):
                return None
            if a <= 0 and b <= 0:
                return None
            return ((a + b) / 2.0, total)
    return None


def collect():
    pts = []
    for cat, series_list in CATEGORIES.items():
        for s in series_list:
            try:
                ms = get(f"{KALSHI}/markets?series_ticker={s}&status=settled&limit={MAX_PER_SERIES}").get("markets", [])
            except Exception:
                continue
            kept = 0
            for m in ms:
                r = m.get("result")
                if r not in ("yes", "no"):
                    continue
                el = early_line(s, m)
                if el is None:
                    continue
                p, vol = el
                pts.append({"cat": cat, "series": s, "p": p, "y": 1 if r == "yes" else 0, "vol": vol})
                kept += 1
            print(f"  {cat:<8} {s:<20} {kept:>3} pts", file=sys.stderr)
    return pts


def calib_table(pts, label):
    print(f"\n=== {label}  (n={len(pts)}) ===")
    if len(pts) < 25:
        print("  too few points"); return
    print(f"  {'price bin':>9} {'n':>4} {'meanP':>7} {'emp':>7} {'gap':>7} {'EV(fade/back)':>14}")
    for i in range(10):
        lo, hi = i / 10, (i + 1) / 10
        g = [x for x in pts if lo <= x["p"] < hi or (hi == 1.0 and x["p"] == 1.0)]
        if len(g) < 5:
            continue
        mp = sum(x["p"] for x in g) / len(g)
        emp = sum(x["y"] for x in g) / len(g)
        gap = emp - mp
        # fade longshot = buy NO: EV ≈ (p - emp) - fee ; back favorite = buy YES: EV ≈ (emp - p) - fee
        ev = (-gap - fee(mp)) if mp < 0.5 else (gap - fee(mp))
        side = "fadeNO" if mp < 0.5 else "backYES"
        print(f"  {lo:.1f}-{hi:.1f} {len(g):>4} {mp:>7.3f} {emp:>7.3f} {gap:>+7.3f} "
              f"{side}:{ev*100:>+6.1f}c")


def tail_summary(pts, label):
    lo = [x for x in pts if x["p"] < 0.30]
    hi = [x for x in pts if x["p"] > 0.70]
    out = []
    if len(lo) >= 10:
        gap = sum(x["y"] - x["p"] for x in lo) / len(lo)
        ev = sum((x["p"] - x["y"]) - fee(x["p"]) for x in lo) / len(lo)
        out.append(f"longshots(n={len(lo)}) gap={gap:+.3f} fadeNO_EV={ev*100:+.1f}c")
    if len(hi) >= 10:
        gap = sum(x["y"] - x["p"] for x in hi) / len(hi)
        ev = sum((x["y"] - x["p"]) - fee(x["p"]) for x in hi) / len(hi)
        out.append(f"favorites(n={len(hi)}) gap={gap:+.3f} backYES_EV={ev*100:+.1f}c")
    print(f"  {label:<20} " + " | ".join(out) if out else f"  {label}: too few tail points")


def main():
    pts = collect()
    sports = [x for x in pts if x["cat"] == "sports"]
    weather = [x for x in pts if x["cat"] == "weather"]
    calib_table(sports, "SPORTS calibration")
    calib_table(weather, "WEATHER calibration")

    print("\n=== Tail bias + fee-adjusted EV (gap = empirical - price) ===")
    print("  (longshot bias => longshot gap < 0; favorite bias => favorite gap > 0)")
    tail_summary(sports, "sports (all)")
    tail_summary(weather, "weather (all)")

    if len(sports) >= 30:
        vols = sorted(x["vol"] for x in sports)
        t1, t2 = vols[len(vols) // 3], vols[2 * len(vols) // 3]
        print("\n=== SPORTS by volume tier (testing 'low-mid vol = more bias') ===")
        tail_summary([x for x in sports if x["vol"] <= t1], f"low vol (<= {t1:.0f})")
        tail_summary([x for x in sports if t1 < x["vol"] <= t2], f"mid vol")
        tail_summary([x for x in sports if x["vol"] > t2], f"high vol (> {t2:.0f})")


if __name__ == "__main__":
    main()
