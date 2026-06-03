#!/usr/bin/env python3
"""Finding-producing scanners. Each returns a list of structured findings:
  {scanner, kind, key, summary, edge_c, legs:[{action,ticker,price_c,url}], detail}
Trustworthy signals only: executable LOCKs (hard arb) and center-vs-spot
divergence using each ladder's OWN width (the method proven artifact-free)."""
import common


def _leg(action_tuple, ticker, url):
    label, price = action_tuple
    return {"action": label, "ticker": ticker, "price_c": round(price * 100), "url": url}


def _lock_finding(scanner, big, small, cost):
    return {
        "scanner": scanner, "kind": "LOCK",
        "key": "lock:" + ":".join(sorted([big["ticker"], small["ticker"]])),
        "summary": f"Nesting lock: {big['ticker']} ⊇ {small['ticker']}",
        "edge_c": round((1.0 - cost) * 100, 1),
        "legs": [_leg(big["yes_act"], big["ticker"], big["url"]),
                 _leg(small["no_act"], small["ticker"], small["url"])],
        "detail": f"Guaranteed ≥$1 payout for ${cost:.2f}. Verify size before trading.",
    }


def _within_ladder_locks(scanner, rows, min_size, min_lock_c):
    out = []
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            low, high = rows[i], rows[j]            # K_low < K_high -> {S>K_low} bigger
            if low["sz"] < min_size or high["sz"] < min_size:
                continue
            cost = low["yes_act"][1] + high["no_act"][1]
            if cost < 1.0 - min_lock_c / 100.0:
                out.append(_lock_finding(scanner, low, high, cost))
    return out


def scan_ladder_vs_spot(u, T):
    """LOCKs + center-vs-spot divergence for one underlying (crypto/commodity)."""
    out = []
    try:
        spot, age = common.pyth_price(u["feed"])
    except Exception:
        return out
    if spot <= 0 or age > T["max_feed_age"]:
        return out
    for series in u["series"]:
        try:
            events = common.open_events(series)
        except Exception:
            continue
        for ev in events:
            rows = common.normalize_event(ev)
            if len(rows) < 5:
                continue
            mu, sig = common.fit_normal(rows)
            if not sig:
                continue
            out += _within_ladder_locks(u["label"], rows, T["min_size_lock"], T["min_lock_c"])
            # CENTER: require a WHOLE-ladder shift vs spot (not one stale strike),
            # then emit ONE finding for the best genuinely-fillable strike.
            if abs(mu - spot) <= T["z_min"] * sig:
                continue
            best = None
            for r in rows:
                if r["sz"] < T["min_size_center"] or r["hs"] > T["max_hs"] or not (0.05 < r["q"] < 0.95):
                    continue
                fair = 1.0 - common.Phi((r["K"] - spot) / sig)   # center=SPOT, width=own sigma
                edge = fair - r["q"]
                if abs(edge) > r["hs"] + T["band"] and abs(edge) * 100 >= T["min_edge_c"]:
                    if best is None or abs(edge) > abs(best[1]):
                        best = (r, edge, fair)
            if best:
                r, edge, fair = best
                act = r["yes_act"] if edge > 0 else r["no_act"]
                out.append({
                    "scanner": u["label"], "kind": "CENTER",
                    "key": f"center:{ev['event_ticker']}:{'Y' if edge > 0 else 'N'}",
                    "summary": f"{u['label']} ladder lagging spot {spot:.1f} (center {mu:.1f})",
                    "edge_c": round(edge * 100, 1),
                    "legs": [_leg(act, r["ticker"], r["url"])],
                    "detail": f"Whole ladder centered {mu:.1f} vs spot {spot:.1f} "
                              f"({(mu-spot)/sig:+.2f} sigma). Best strike K={r['K']:.0f}: "
                              f"fair {fair*100:.1f}% vs market {r['q']*100:.1f}%.",
                })
    return out


def scan_complete_set(T):
    """Sweep ALL open events for complete-set mispricing in mutually-exclusive
    (and collectively exhaustive) events:
      YES side: buy YES on every outcome -> $1 payout. Arb if sum(yes_ask)+fees<$1.
      NO  side: buy NO on every outcome  -> (N-1) payout. Arb if sum(no_ask)+fees<N-1.
    Exhaustiveness guard: 'mutually_exclusive' != collectively exhaustive (a wide
    field sums far below $1 and looks like a fake 90c arb), so require YES gross
    >= cs_min_gross. NO side is naturally immune."""
    out = []
    cursor, pages = "", 0
    while pages < T["cs_max_pages"]:
        pages += 1
        url = f"{common.KALSHI}/events?limit=200&status=open&with_nested_markets=true"
        if cursor:
            url += "&cursor=" + cursor
        try:
            d = common.http_get_json(url)
        except Exception:
            break
        for ev in d.get("events", []):
            if not ev.get("mutually_exclusive"):
                continue
            mkts = ev.get("markets", [])
            if len(mkts) < 2:
                continue
            out += _complete_set_yes(ev, mkts, T)
            out += _complete_set_no(ev, mkts, T)
        cursor = d.get("cursor") or ""
        if not cursor:
            break
    return out


def _legs_priced(mkts, ask_key, size_key):
    legs = []
    for m in mkts:
        try:
            a = float(m[ask_key]); sz = float(m.get(size_key) or 0)
        except (TypeError, ValueError, KeyError):
            return None
        if not (0.0 < a < 1.0):
            return None
        legs.append((a, sz, m))
    return legs


def _complete_set_yes(ev, mkts, T):
    legs = _legs_priced(mkts, "yes_ask_dollars", "yes_ask_size_fp")
    if not legs or any(sz < T["min_size_lock"] for _, sz, _ in legs):
        return []
    gross = sum(a for a, _, _ in legs)
    net = sum(a + common.kalshi_fee(a) for a, _, _ in legs)
    if gross < T["cs_min_gross"] or net >= 1.0 - T["min_lock_c"] / 100.0:
        return []
    return [{
        "scanner": "complete-set", "kind": "LOCK",
        "key": "cs-yes:" + ev["event_ticker"],
        "summary": f"Complete-set (YES) {ev['event_ticker']}: sum={gross:.3f} < $1",
        "edge_c": round((1.0 - net) * 100, 1),
        "legs": [{"action": "BUY YES", "ticker": m["ticker"],
                  "price_c": round(a * 100), "url": common.kalshi_url(m["ticker"])}
                 for a, _, m in legs],
        "detail": f"Buy YES on all {len(legs)} outcomes; net ${net:.2f} for $1. "
                  f"VERIFY the event is collectively exhaustive (no missing outcome) + size.",
    }]


def _complete_set_no(ev, mkts, T):
    legs = _legs_priced(mkts, "no_ask_dollars", "yes_bid_size_fp")  # buy NO lifts yes bids
    if not legs or any(sz < T["min_size_lock"] for _, sz, _ in legs):
        return []
    n = len(legs)
    net = sum(a + common.kalshi_fee(a) for a, _, _ in legs)
    if net >= (n - 1) - T["min_lock_c"] / 100.0:
        return []
    return [{
        "scanner": "complete-set", "kind": "LOCK",
        "key": "cs-no:" + ev["event_ticker"],
        "summary": f"Complete-set (NO) {ev['event_ticker']}: sum={net:.3f} < {n-1}",
        "edge_c": round(((n - 1) - net) * 100, 1),
        "legs": [{"action": "BUY NO", "ticker": m["ticker"],
                  "price_c": round(a * 100), "url": common.kalshi_url(m["ticker"])}
                 for a, _, m in legs],
        "detail": f"Buy NO on all {n} outcomes; net ${net:.2f} for ${n-1} payout. Verify size.",
    }]


def scan_nesting(series_list, T):
    """Cumulative-nesting LOCKs (deadline ⊇ deadline, or threshold ⊇ threshold)."""
    out = []
    for s in series_list:
        try:
            events = common.open_events(s)
        except Exception:
            continue
        for ev in events:
            legs = []
            for m in ev["markets"]:
                rank = common.nesting_rank(m.get("yes_sub_title") or "", m)
                if rank is None:
                    continue
                try:
                    ya = float(m["yes_ask_dollars"]); na = float(m["no_ask_dollars"])
                    sz = float(m.get("yes_ask_size_fp") or 0)
                except (TypeError, ValueError, KeyError):
                    continue
                if sz <= 0 or ya >= 1.0:
                    continue
                legs.append({"rank": rank, "ticker": m["ticker"], "sz": sz,
                             "yes_act": ("BUY YES", ya), "no_act": ("BUY NO", na),
                             "url": common.kalshi_url(m["ticker"])})
            legs.sort(key=lambda r: r["rank"])
            for i in range(len(legs)):
                for j in range(i + 1, len(legs)):
                    small, big = legs[i], legs[j]      # higher rank = bigger set
                    if big["sz"] < T["min_size_lock"] or small["sz"] < T["min_size_lock"]:
                        continue
                    cost = big["yes_act"][1] + small["no_act"][1]
                    if cost < 1.0 - T["min_lock_c"] / 100.0:
                        out.append(_lock_finding("nesting", big, small, cost))
    return out
