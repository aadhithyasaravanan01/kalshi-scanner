#!/usr/bin/env python3
"""Shared helpers: HTTP, Pyth, Kalshi fetch, survival-function normalization,
Normal fit, Kalshi URL builder. Stdlib only (no external dependencies)."""
import json, math, re, time, urllib.request

KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
HERMES = "https://hermes.pyth.network/v2"
UA = {"User-Agent": "kalshi-arb-scanner/1.0", "Accept": "application/json"}

MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}


def http_get_json(url, timeout=20):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return json.loads(r.read().decode())


def Phi(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def yes_mid(ya, na):
    return (ya + (1.0 - na)) / 2.0


def pyth_price(feed):
    d = http_get_json(f"{HERMES}/updates/price/latest?ids[]={feed}")
    p = d["parsed"][0]["price"]
    return int(p["price"]) * 10 ** int(p["expo"]), int(time.time()) - int(p["publish_time"])


def open_events(series):
    d = http_get_json(f"{KALSHI}/events?series_ticker={series}&status=open&with_nested_markets=true")
    return [e for e in d.get("events", []) if e.get("markets")]


def kalshi_url(ticker):
    """Best-effort market link from a market/event ticker (series-level page)."""
    series = ticker.split("-")[0]
    return f"https://kalshi.com/markets/{series.lower()}"


def _row(ticker, K, q, sz, ya, na, acquire_yes_label, acquire_no_label):
    """A survival-function point for event {S>K}. acquire_* tuples are the
    (Kalshi button, price$) you press to get long / short that event."""
    return {"ticker": ticker, "K": K, "q": q, "sz": sz,
            "hs": abs(ya - (1 - na)) / 2.0,
            "yes_act": acquire_yes_label, "no_act": acquire_no_label,
            "url": kalshi_url(ticker)}


def normalize_event(ev):
    """Markets -> survival rows for P(S>K), handling 'above K' and 'below K'.
    Each row carries the exact Kalshi action+price to go long/short {S>K}."""
    rows = []
    for m in ev["markets"]:
        fs, cs = m.get("floor_strike"), m.get("cap_strike")
        try:
            ya = float(m["yes_ask_dollars"]); na = float(m["no_ask_dollars"])
            sz = float(m.get("yes_ask_size_fp") or 0)
        except (TypeError, ValueError, KeyError):
            continue
        ym = yes_mid(ya, na)
        if fs is not None and cs is None:          # "above K": YES == S>K
            rows.append(_row(m["ticker"], float(fs), ym, sz, ya, na,
                             ("BUY YES", ya), ("BUY NO", na)))
        elif cs is not None and fs is None:        # "below K": S>K via BUY NO
            rows.append(_row(m["ticker"], float(cs), 1.0 - ym, sz, ya, na,
                             ("BUY NO", na), ("BUY YES", ya)))
    rows.sort(key=lambda r: r["K"])
    return rows


def fit_normal(rows):
    info = [r for r in rows if 0.04 < r["q"] < 0.96]
    if len(info) < 4:
        return None, None
    lo = min(r["K"] for r in info); hi = max(r["K"] for r in info)
    span = max(hi - lo, 1.0)
    mus = [lo - 0.5 * span + 2 * span * i / 180 for i in range(180)]
    sigs = [span / 80 * (1 + i) for i in range(160)]
    best = (1e18, None, None)
    for mu in mus:
        for s in sigs:
            e = sum((r["q"] - (1 - Phi((r["K"] - mu) / s))) ** 2 for r in info)
            if e < best[0]:
                best = (e, mu, s)
    return best[1], best[2]


def nesting_rank(subtitle, market):
    """Containment rank for nesting: LARGER = bigger event set (more likely).
    Handles deadline ('before <month> <year>') and 'above K' thresholds."""
    s = subtitle.lower()
    md = re.search(r"(?:before|by)\s+([a-z]+)\s+(\d{4})", s)
    if md and md.group(1) in MONTHS:
        return int(md.group(2)) * 12 + MONTHS[md.group(1)]
    fs = market.get("floor_strike")
    if fs is not None and market.get("cap_strike") is None:
        return -float(fs)
    return None
