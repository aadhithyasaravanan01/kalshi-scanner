#!/usr/bin/env python3
"""Favorite-longshot calibration test on Kalshi — DEFINITIVE (pre-game line).

Earlier passes used a life-fraction or "early line" price, which is noisy and
sign-unstable. This version snapshots each settled SPORTS market at its
PRE-GAME CLOSING LINE: the price a few hours before settlement, anchored to the
game's actual schedule (occurrence_datetime, which ~= game end) minus LEAD_H.
That lands just before tip-off for typical game lengths, before in-play prices
converge to 0/1 — the cleanest "market belief" snapshot available.

Reports: calibration by price decile, BOTH tails (longshot overpricing &
favorite underpricing), volume-tier segmentation, and fee-adjusted EV.
"""
import json, urllib.request, calendar, datetime, sys

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
UA = {"User-Agent": "longshot-backtest/3.0"}
SPORTS = ["KXNBAGAME", "KXMLBGAME", "KXNHLGAME", "KXATPMATCH", "KXBRASILEIROGAME",
          "KXBELGIANPLGAME", "KXALEAGUEGAME", "KXACBGAME", "KXBSLGAME"]
MAX_PER_SERIES = 90
LEAD_H = 3.0              # snapshot this many hours before occurrence (~game end)
NEAR_WINDOW = 7200        # accept nearest candle within 2h of the target time
MIN_VOL = 20.0            # require some real trading to trust the price


def get(url):
    return json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20).read())


def ts(s):
    return calendar.timegm(datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timetuple())


def fee(p):
    return 0.07 * p * (1.0 - p)


def pregame_line(series, m):
    anchor = m.get("occurrence_datetime") or m.get("close_time")
    if not anchor:
        return None
    try:
        a, o, c = ts(anchor), ts(m["open_time"]), ts(m["close_time"])
    except Exception:
        return None
    snap = a - LEAD_H * 3600
    if snap <= o + 600:               # market must predate the snapshot
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
        return None                   # no candle near the pre-game snapshot
    try:
        ya = float(best["yes_ask"]["close_dollars"]); yb = float(best["yes_bid"]["close_dollars"])
    except (KeyError, TypeError, ValueError):
        return None
    if ya <= 0 and yb <= 0:
        return None
    return ((ya + yb) / 2.0, total)


def collect():
    pts = []
    for s in SPORTS:
        try:
            ms = get(f"{KALSHI}/markets?series_ticker={s}&status=settled&limit={MAX_PER_SERIES}").get("markets", [])
        except Exception:
            continue
        kept = 0
        for m in ms:
            r = m.get("result")
            if r not in ("yes", "no"):
                continue
            pl = pregame_line(s, m)
            if pl is None:
                continue
            p, vol = pl
            pts.append({"series": s, "p": p, "y": 1 if r == "yes" else 0, "vol": vol})
            kept += 1
        print(f"  {s:<20} {kept:>3} pts", file=sys.stderr)
    return pts


def calib(pts, label):
    print(f"\n=== {label}  (n={len(pts)}) ===")
    if len(pts) < 25:
        print("  too few points"); return
    print(f"  {'bin':>9} {'n':>4} {'meanP':>7} {'emp':>7} {'gap':>7} {'fee-adj EV':>12}")
    for i in range(10):
        lo, hi = i / 10, (i + 1) / 10
        g = [x for x in pts if lo <= x["p"] < hi or (hi == 1.0 and x["p"] == 1.0)]
        if len(g) < 6:
            continue
        mp = sum(x["p"] for x in g) / len(g)
        emp = sum(x["y"] for x in g) / len(g)
        gap = emp - mp
        ev = (-gap - fee(mp)) if mp < 0.5 else (gap - fee(mp))
        tag = "fadeNO" if mp < 0.5 else "backYES"
        print(f"  {lo:.1f}-{hi:.1f} {len(g):>4} {mp:>7.3f} {emp:>7.3f} {gap:>+7.3f}  {tag}:{ev*100:>+5.1f}c")


def tails(pts, label):
    lo = [x for x in pts if x["p"] < 0.30]
    hi = [x for x in pts if x["p"] > 0.70]
    parts = []
    if len(lo) >= 10:
        gap = sum(x["y"] - x["p"] for x in lo) / len(lo)
        ev = sum((x["p"] - x["y"]) - fee(x["p"]) for x in lo) / len(lo)
        parts.append(f"longshots n={len(lo)} gap={gap:+.3f} fadeNO_EV={ev*100:+.1f}c")
    if len(hi) >= 10:
        gap = sum(x["y"] - x["p"] for x in hi) / len(hi)
        ev = sum((x["y"] - x["p"]) - fee(x["p"]) for x in hi) / len(hi)
        parts.append(f"favorites n={len(hi)} gap={gap:+.3f} backYES_EV={ev*100:+.1f}c")
    print(f"  {label:<22} " + (" | ".join(parts) if parts else "too few tail points"))


def main():
    pts = collect()
    calib(pts, "SPORTS pre-game line")
    print("\n=== Tail bias + fee-adjusted EV (longshot bias => longshot gap<0; favorite bias => favorite gap>0) ===")
    tails(pts, "all sports")
    if len(pts) >= 40:
        vols = sorted(x["vol"] for x in pts)
        t1, t2 = vols[len(vols) // 3], vols[2 * len(vols) // 3]
        print("\n=== by volume tier (test: low/mid vol = more bias?) ===")
        tails([x for x in pts if x["vol"] <= t1], f"low vol (<= {t1:.0f})")
        tails([x for x in pts if t1 < x["vol"] <= t2], "mid vol")
        tails([x for x in pts if x["vol"] > t2], f"high vol (> {t2:.0f})")


if __name__ == "__main__":
    main()
