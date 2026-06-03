#!/usr/bin/env python3
"""One-shot scan: run every scanner once, alert NEW findings to Discord, and
write results.json. This is the GitHub Actions entry point (cron). Run locally
with DRY_RUN=1 to print instead of posting."""
import json, time
import config, scanners, alerts


def _safe(name, fn):
    """A transient error in one scanner must never fail the whole run."""
    try:
        return fn()
    except Exception as e:
        print(f"[scan error] {name}: {type(e).__name__}: {e}")
        return []


def run():
    findings = []
    for u in config.LADDER_VS_SPOT:
        findings += _safe(f"ladder:{u['label']}",
                          lambda u=u: scanners.scan_ladder_vs_spot(u, config.THRESH))
    findings += _safe("nesting", lambda: scanners.scan_nesting(config.NESTING_SERIES, config.THRESH))
    findings += _safe("complete-set", lambda: scanners.scan_complete_set(config.THRESH))

    findings.sort(key=lambda f: -abs(f.get("edge_c", 0)))
    with open("results.json", "w") as f:
        json.dump({"generated_unix": int(time.time()), "count": len(findings),
                   "findings": findings}, f, indent=2)

    sent = alerts.alert_findings(findings)
    locks = sum(1 for f in findings if f["kind"] == "LOCK")
    print(f"{len(findings)} findings ({locks} locks) | {sent} new alert(s) sent.")
    for f in findings[:10]:
        print(f"  [{f['kind']}] {f['summary']}  edge={f.get('edge_c', 0):+.1f}c")
    return findings


if __name__ == "__main__":
    run()
