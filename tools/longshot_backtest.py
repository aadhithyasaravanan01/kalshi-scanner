#!/usr/bin/env python3
"""Favorite-longshot test on Kalshi — DEFINITIVE + low-volume deep dive.

Snapshots each settled sports market at its PRE-GAME closing line
(occurrence_datetime - LEAD_H, anchored to the game schedule). Auto-discovers
ALL moneyline leagues (category=Sports) to maximize the low-volume long tail,
then significance-tests the fee-adjusted EV of the implied strategies per volume
tier, with 95% confidence intervals. An edge is only real if its CI excludes 0.
"""
import json, urllib.request, calendar, datetime, math, sys

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "longshot-backtest/4.0"}
MAX_SERIES = 160
PER_SERIES = 30
TOTAL_CAP = 2600          # markets processed (bounds runtime)
LEAD_H = 3.0
NEAR_WINDOW = 7200
MIN_VOL = 15.0


def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read())


def ts(s):
    return calendar.timegm(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timetuple())


def fee(p):
    return 0.07 * p * (1.0 - p)


def discover():
    try:
        s = get(f"{KALSHI}/series?category=Sports").get("series", [])
    except Exception:
        return []
    bad = ("SPREAD", "TOTAL", "EXACT", "ROUND", "SCORE", "FIRST", "PROP", "MVP",
           "SERIES", "DISTANCE", "METHOD", "MINUTE", "KNOCKOUT")
    out = [x["ticker"] for x in s
           if (x["ticker"].endswith("GAME") or x["ticker"].endswith("MATCH"))
           and not any(b in x["ticker"] for b in bad)]
    return out[:MAX_SERIES]


def pregame_line(series, m):
    anchor = m.get("occurrence_datetime") or m.get("close_time")
    if not anchor:
        return None
    try:
        a, o, c = ts(anchor), ts(m["open_time"]), ts(m["close_time"])
    except Exception:
        return None
    snap = a - LEAD_H * 3600
    if snap <= o + 600:
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
    if total < MIN_VOL:
        return None
    best = min(cs, key=lambda x: abs(float(x.get("end_period_ts", 0)) - snap))
    if abs(float(best.get("end_period_ts", 0)) - snap) > NEAR_WINDOW:
        return None
    try:
        ya = float(best["yes_ask"]["close_dollars"]); yb = float(best["yes_bid"]["close_dollars"])
    except (KeyError, TypeError, ValueError):
        return None
    if ya <= 0 and yb <= 0:
        return None
    return ((ya + yb) / 2.0, ya, yb, total)


def collect():
    series = discover()
    print(f"discovered {len(series)} moneyline series", file=sys.stderr)
    pts, processed = [], 0
    for s in series:
        if processed >= TOTAL_CAP:
            break
        try:
            ms = get(f"{KALSHI}/markets?series_ticker={s}&status=settled&limit={PER_SERIES}").get("markets", [])
        except Exception:
            continue
        kept = 0
        for m in ms:
            if processed >= TOTAL_CAP:
                break
            if m.get("result") not in ("yes", "no"):
                continue
            processed += 1
            pl = pregame_line(s, m)
            if pl is None:
                continue
            p, ask, bid, vol = pl
            pts.append({"p": p, "ask": ask, "bid": bid,
                        "y": 1 if m["result"] == "yes" else 0, "vol": vol})
            kept += 1
        if kept:
            print(f"  {s:<22} {kept:>3} (total kept {len(pts)}, processed {processed})", file=sys.stderr)
    return pts


def ev_ci(evs):
    """(n, mean_cents, lo95_cents, hi95_cents)."""
    n = len(evs)
    if n < 2:
        return n, 0, 0, 0
    m = sum(evs) / n
    var = sum((e - m) ** 2 for e in evs) / (n - 1)
    se = math.sqrt(var / n)
    return n, m * 100, (m - 1.96 * se) * 100, (m + 1.96 * se) * 100


def tier_report(pts, label):
    lo = [x for x in pts if x["p"] < 0.30]
    hi = [x for x in pts if x["p"] > 0.70]
    # MID-price EV (theoretical) vs EXECUTABLE EV (cross the spread + fee):
    #   fade longshot = buy NO at no_ask = 1 - yes_bid
    #   back favorite = buy YES at yes_ask
    fade_mid = [(x["p"] - x["y"]) - fee(x["p"]) for x in lo]
    back_mid = [(x["y"] - x["p"]) - fee(x["p"]) for x in hi]
    fade_exe = [(x["bid"] - x["y"]) - fee(1 - x["bid"]) for x in lo]
    back_exe = [(x["y"] - x["ask"]) - fee(x["ask"]) for x in hi]
    avg_spread_lo = sum(x["ask"] - x["bid"] for x in lo) / len(lo) if lo else 0
    avg_spread_hi = sum(x["ask"] - x["bid"] for x in hi) / len(hi) if hi else 0
    print(f"\n  [{label}]  (n={len(pts)})  avg spread: longshots {avg_spread_lo*100:.1f}c, favorites {avg_spread_hi*100:.1f}c")
    for name, mid, exe in (("fade longshots (buy NO) ", fade_mid, fade_exe),
                           ("back favorites (buy YES)", back_mid, back_exe)):
        if len(exe) < 10:
            print(f"    {name}: too few (n={len(exe)})"); continue
        _, mm, _, _ = ev_ci(mid)
        n, em, el, eh = ev_ci(exe)
        sig = "  ** SIGNIFICANT +EV **" if el > 0 else ("  (sig LOSS)" if eh < 0 else "")
        print(f"    {name}: n={n:>4}  mid EV={mm:+5.2f}c | EXEC EV={em:+5.2f}c "
              f"95% CI [{el:+5.2f}, {eh:+5.2f}]c{sig}")


def main():
    pts = collect()
    print(f"\n==== TOTAL usable points: {len(pts)} ====")
    if len(pts) < 50:
        print("too few"); return
    tier_report(pts, "ALL")
    vols = sorted(x["vol"] for x in pts)
    t1, t2 = vols[len(vols) // 3], vols[2 * len(vols) // 3]
    tier_report([x for x in pts if x["vol"] <= t1], f"LOW vol <= {t1:.0f}")
    tier_report([x for x in pts if t1 < x["vol"] <= t2], "MID vol")
    tier_report([x for x in pts if x["vol"] > t2], f"HIGH vol > {t2:.0f}")
    print("\nAn edge is real only if its 95% CI excludes 0 (and is positive).")


if __name__ == "__main__":
    main()
