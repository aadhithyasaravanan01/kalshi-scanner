#!/usr/bin/env python3
"""What to scan. Pyth feed ids are the EXACT settlement references Kalshi uses
(so a divergence is a real lag, not a proxy mismatch)."""

# Pyth feed ids (settlement references)
BTC = "e62df6c8b4a85fe1a67db44dc12de5db330f7ac66b72dc658afedf0f4a415b43"  # BTC/USD
ETH = "ff61491a931112ddf1bd8147cd1b641375f79f5825126d665480874634fd0ace"  # ETH/USD
XAU = "765d2ba906dbc32ca17cc11f5310a89e9ee1f6420508c63861f2f8ba4ee34bb2"  # gold  (KXGOLDD)
XAG = "f2fb02c32b055c805e7238d628e5e9dadef274376114eb1f012337cabe93871e"  # silver(KXSILVERD)

# Underlyings with a live, exact spot feed (crypto 24/7; metals 24/5).
LADDER_VS_SPOT = [
    {"label": "BTC",    "series": ["KXBTCD"],   "feed": BTC},
    {"label": "ETH",    "series": ["KXETHD"],   "feed": ETH},
    {"label": "gold",   "series": ["KXGOLDD"],  "feed": XAU},
    {"label": "silver", "series": ["KXSILVERD"], "feed": XAG},
    # WTI omitted: Kalshi settles on ICE, Pyth WTI is only a proxy -> false signals.
]

# Cumulative-nesting families (deadline ladders, threshold ladders).
NESTING_SERIES = ["KXBTCMAX100", "KXETHMAXY", "KXRAINNYCM"]

# Thresholds (tuned to keep alerts rare + trustworthy). Center alerts are the
# soft signal, so they need real liquidity AND a whole-ladder shift; thin
# just-opened ladders (which sit stale vs spot) must NOT trip them.
THRESH = {
    "min_size_lock": 20.0,    # depth for a hard lock (smaller ok — it's guaranteed)
    "min_size_center": 100.0,  # depth for a center alert (must be genuinely liquid)
    "band": 0.03,             # model-error cushion beyond half-spread
    "max_hs": 0.02,           # skip wide/stale quotes
    "min_edge_c": 8.0,        # center alerts must clear 8c
    "z_min": 0.25,            # require |mu - spot| > z_min * sigma (whole-ladder lag)
    "min_lock_c": 1.0,        # locks must clear 1c
    "max_feed_age": 90,       # seconds; ignore stale Pyth ticks
}
