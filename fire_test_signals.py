# fire_test_signals.py — Blast test signals to TradersPost
# Run this to verify your webhook is routing correctly.
# It sends a rapid series of BUY/SELL signals so you can see them arrive.
#
# Usage:
#   python fire_test_signals.py
#
# Set these env vars (or it reads from your config):
#   TRADERSPOST_WEBHOOK_URL=https://traderspost.io/...
#   TRADERSPOST_PASSWORD=yourpassword
#   TEST_TICKER=MGC          (optional, defaults to MGC)
#   TEST_QUANTITY=1           (optional, defaults to 1)

import os
import sys
import time
import json
import requests
from datetime import datetime

# ── Try to import from your existing config ──
WEBHOOK_URL = os.environ.get("TRADERSPOST_WEBHOOK_URL", "")
PASSWORD = os.environ.get("TRADERSPOST_PASSWORD", "")
TICKER = os.environ.get("TEST_TICKER", "MGC")
QUANTITY = int(os.environ.get("TEST_QUANTITY", "1"))

# If env vars aren't set, try to pull from config.py
if not WEBHOOK_URL:
    try:
        from config import BROKERS
        for bid, cfg in BROKERS.items():
            if cfg.get("type") == "webhook":
                WEBHOOK_URL = cfg.get("webhook_url", "")
                PASSWORD = cfg.get("password", "")
                TICKER = cfg.get("ticker", TICKER)
                print(f"Found webhook config from broker '{bid}'")
                break
    except Exception as e:
        print(f"Could not import config: {e}")

if not WEBHOOK_URL:
    print("ERROR: No webhook URL found.")
    print("Set TRADERSPOST_WEBHOOK_URL env var or check config.py")
    sys.exit(1)

print("=" * 60)
print("  TRADERSPOST WEBHOOK TEST")
print("=" * 60)
print(f"  URL:      {WEBHOOK_URL[:50]}...")
print(f"  Ticker:   {TICKER}")
print(f"  Quantity: {QUANTITY}")
print(f"  Password: {'***' + PASSWORD[-3:] if len(PASSWORD) > 3 else '(empty)'}")
print("=" * 60)

# ── Test signals to fire ──
TEST_SIGNALS = [
    {"action": "buy",  "label": "TEST BUY #1 — basic long entry"},
    {"action": "sell",  "label": "TEST SELL #1 — close the long"},
    {"action": "sell", "label": "TEST SELL #2 — short entry"},
    {"action": "buy",  "label": "TEST BUY #2 — close the short"},
    {"action": "buy",  "label": "TEST BUY #3 — another long"},
    {"action": "sell",  "label": "TEST SELL #3 — flat again"},
]

results = []

for i, sig in enumerate(TEST_SIGNALS, 1):
    payload = {
        "password": PASSWORD,
        "ticker": TICKER,
        "action": sig["action"],
        "quantity": QUANTITY,
    }

    print(f"\n── Signal {i}/{len(TEST_SIGNALS)}: {sig['label']} ──")
    print(f"   Payload: {json.dumps(payload)}")

    try:
        r = requests.post(WEBHOOK_URL, json=payload, timeout=10)
        status = r.status_code
        body = r.text[:300]
        ok = status == 200

        results.append({"signal": sig["label"], "status": status, "ok": ok, "response": body})

        if ok:
            print(f"   ✅ HTTP {status} — SUCCESS")
        else:
            print(f"   ❌ HTTP {status} — FAILED")
        print(f"   Response: {body}")

    except requests.exceptions.ConnectionError as e:
        print(f"   ❌ CONNECTION ERROR — webhook URL unreachable")
        print(f"   {e}")
        results.append({"signal": sig["label"], "status": 0, "ok": False, "response": str(e)})
    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        results.append({"signal": sig["label"], "status": 0, "ok": False, "response": str(e)})

    # Small delay between signals so TradersPost doesn't rate-limit
    if i < len(TEST_SIGNALS):
        print(f"   Waiting 3 seconds...")
        time.sleep(3)

# ── Summary ──
print(f"\n{'=' * 60}")
print(f"  RESULTS SUMMARY")
print(f"{'=' * 60}")
passed = sum(1 for r in results if r["ok"])
failed = len(results) - passed

for r in results:
    icon = "✅" if r["ok"] else "❌"
    print(f"  {icon} {r['signal']} → HTTP {r['status']}")

print(f"\n  {passed}/{len(results)} signals delivered successfully")

if failed > 0:
    print(f"\n  ⚠️  {failed} signal(s) FAILED. Check:")
    print(f"     1. Is the webhook URL correct?")
    print(f"     2. Is the password correct?")
    print(f"     3. Is TradersPost expecting this ticker ({TICKER})?")
    print(f"     4. Is your TradersPost strategy active/enabled?")
else:
    print(f"\n  🎉 All signals delivered! Check TradersPost dashboard to")
    print(f"     confirm they were received and routed to your broker.")

print(f"{'=' * 60}")
