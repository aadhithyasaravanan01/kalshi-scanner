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
