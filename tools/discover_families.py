#!/usr/bin/env python3
"""Discover related-market families: series that settle on the SAME underlying
(same settlement source) but at DIFFERENT horizons (daily/weekly/monthly/...).
Those are exactly the families where one contract should price another."""
import json, urllib.request
from collections import defaultdict

K = "https://api.elections.kalshi.com/trade-api/v2"


def get(u):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(u, headers={"User-Agent": "disc/1.0"}), timeout=20).read())


CATS = ["Commodities", "Financials", "Economics", "Crypto", "Climate and Weather"]
families = defaultdict(list)   # underlying-key -> [(ticker, freq, title)]

for cat in CATS:
    try:
        s = get(f"{K}/series?category={cat.replace(' ', '%20')}").get("series", [])
    except Exception as e:
        print(f"[{cat}] error {e}"); continue
    for x in s:
        src = x.get("settlement_sources") or [{}]
        key = (src[0].get("url") or src[0].get("name") or "?").strip()
        families[(cat, key)].append((x["ticker"], x.get("frequency", "?"), x.get("title", "")[:30]))
    print(f"[{cat}] {len(s)} series")

print("\n=== MULTI-HORIZON FAMILIES (same settlement source, >=2 frequencies) ===")
for (cat, key), members in sorted(families.items()):
    freqs = set(f for _, f, _ in members)
    if len(freqs) >= 2 and len(members) >= 2:
        print(f"\n[{cat}] source={key[:50]}")
        for tk, fr, ti in sorted(members, key=lambda m: m[1]):
            print(f"    {tk:<16} {fr:<8} {ti}")
