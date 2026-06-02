#!/usr/bin/env python3
"""Local CONTINUOUS runner: same scanners as run_scans.py, looped, for watching
live (e.g. overnight on your own machine). Alerts go to Discord just like the
cron path. Ctrl-C to stop. For hands-off running, use the GitHub Actions cron
instead (see .github/workflows/scan.yml)."""
import sys, time
from datetime import datetime, timezone
import run_scans

POLL_SECONDS = 60

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    print(f"Continuous monitor, every {POLL_SECONDS}s. Ctrl-C to stop.")
    while True:
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        try:
            print(f"--- {ts} ---")
            run_scans.run()
        except Exception as e:
            print(f"[{ts}] error: {type(e).__name__}: {e}")
        time.sleep(POLL_SECONDS)
