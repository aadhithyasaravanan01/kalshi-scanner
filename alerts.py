#!/usr/bin/env python3
"""Discord alerting with de-duplication. The webhook URL is read from the
DISCORD_WEBHOOK_URL env var (never committed). Set DRY_RUN=1 to print instead
of posting. State in state/seen.json prevents re-spamming the same finding;
a standing finding re-alerts only every RE_ALERT_HOURS."""
import os, json, time, urllib.request

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
DRY = os.environ.get("DRY_RUN", "") not in ("", "0", "false", "False")
STATE_PATH = "state/seen.json"
RE_ALERT_HOURS = 6


def _post(content):
    if DRY or not WEBHOOK:
        print(f"[alert{' DRY' if DRY else ' NO-WEBHOOK'}]\n{content}\n")
        return 204
    data = json.dumps({"username": "kalshi-arb-scanner", "content": content}).encode()
    req = urllib.request.Request(WEBHOOK, data=data,
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": "kalshi-arb-scanner/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except Exception as e:
        print(f"[discord error] {e}")
        return None


def _load():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save(seen):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(seen, f, indent=0, sort_keys=True)


def format_finding(f):
    icon = "🔒" if f["kind"] == "LOCK" else "🎯"
    lines = [f"{icon} **{f['summary']}**  `{f['scanner']}/{f['kind']}`"]
    if f.get("edge_c"):
        lines.append(f"edge ≈ **{f['edge_c']:+.1f}¢**")
    for leg in f["legs"]:
        lines.append(f"• **{leg['action']}** `{leg['ticker']}` @ {leg['price_c']}¢ — <{leg['url']}>")
    if f.get("detail"):
        lines.append(f"_{f['detail']}_")
    return "\n".join(lines)


def alert_findings(findings):
    seen = _load()
    now = int(time.time())
    sent = 0
    for f in findings:
        last = seen.get(f["key"])
        if last is None or (now - last) > RE_ALERT_HOURS * 3600:
            _post(format_finding(f))
            seen[f["key"]] = now
            sent += 1
    # prune keys older than 7 days
    seen = {k: v for k, v in seen.items() if now - v < 7 * 86400}
    _save(seen)
    return sent
