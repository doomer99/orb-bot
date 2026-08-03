# test_tradier.py — Run this once to diagnose your Tradier connection
# Add to your repo, deploy to Railway, check the logs
# OR run locally: python test_tradier.py

import os
import requests
from datetime import datetime
import pytz

ET = pytz.timezone("America/New_York")

# ── Pull from environment (Railway) or hardcode for local test ──
TOKEN = os.environ.get("TRADIER_TOKEN", "")
ACCOUNT = os.environ.get("TRADIER_ACCOUNT", "")
SANDBOX = os.environ.get("TRADIER_SANDBOX", "true").lower() == "true"

BASE = "https://sandbox.tradier.com/v1" if SANDBOX else "https://api.tradier.com/v1"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
}

print("=" * 50)
print("TRADIER CONNECTION TEST")
print("=" * 50)
print(f"Sandbox: {SANDBOX}")
print(f"Base URL: {BASE}")
print(f"Account: {ACCOUNT}")
print(f"Token: {TOKEN[:6]}...{TOKEN[-4:]}" if len(TOKEN) > 10 else f"Token: '{TOKEN}' ⚠️ TOO SHORT")
print()

# ── Test 1: Profile ──
print("TEST 1: User Profile")
try:
    r = requests.get(f"{BASE}/user/profile", headers=HEADERS, timeout=8)
    print(f"  Status: {r.status_code}")
    print(f"  Body:   {r.text[:200]}")
    if r.status_code == 401:
        print("  ❌ TOKEN IS INVALID OR EXPIRED — get a new one from developer.tradier.com")
        print("  Stopping here — fix the token first.")
        exit()
    elif r.status_code == 200:
        print("  ✅ Token works!")
except Exception as e:
    print(f"  ❌ Error: {e}")
    exit()

print()

# ── Test 2: Account Balance ──
print("TEST 2: Account Balance")
try:
    r = requests.get(f"{BASE}/accounts/{ACCOUNT}/balances", headers=HEADERS, timeout=8)
    print(f"  Status: {r.status_code}")
    print(f"  Body:   {r.text[:300]}")
    if r.status_code == 200:
        print("  ✅ Account ID works!")
    else:
        print("  ❌ BAD ACCOUNT ID — check TRADIER_ACCOUNT in Railway")
        exit()
except Exception as e:
    print(f"  ❌ Error: {e}")
    exit()

print()

# ── Test 3: SPY Quote ──
print("TEST 3: SPY Quote")
try:
    r = requests.get(
        f"{BASE}/markets/quotes",
        headers=HEADERS,
        params={"symbols": "SPY"},
        timeout=5,
    )
    print(f"  Status: {r.status_code}")
    print(f"  Body:   {r.text[:300]}")
    if r.status_code == 200 and r.text.strip():
        data = r.json()
        price = float(data["quotes"]["quote"].get("last", 0))
        print(f"  ✅ SPY price: ${price:.2f}")
    else:
        print("  ⚠️ No quote data — sandbox may not have real-time quotes")
        price = 560  # fallback for test
except Exception as e:
    print(f"  ❌ Error: {e}")
    price = 560

print()

# ── Test 4: Place a test option order ──
print("TEST 4: Place Test Order (1x SPY call)")
strike = round(price)
exp = datetime.now(ET).strftime("%y%m%d")
occ = f"SPY{exp}C{int(strike * 1000):08d}"
print(f"  Symbol: {occ}")
print(f"  Strike: ${strike}")

try:
    r = requests.post(
        f"{BASE}/accounts/{ACCOUNT}/orders",
        headers=HEADERS,
        data={
            "class": "option",
            "symbol": "SPY",
            "option_symbol": occ,
            "side": "buy_to_open",
            "quantity": "1",
            "type": "market",
            "duration": "day",
        },
        timeout=10,
    )
    print(f"  Status: {r.status_code}")
    print(f"  Body:   {r.text[:500]}")

    if not r.text.strip():
        print("  ❌ EMPTY RESPONSE — this is your bug!")
        print("     Tradier returned nothing. Likely causes:")
        print("     - Sandbox token can't place option orders")
        print("     - Account not approved for options")
        print("     - Sandbox is down")
    elif r.status_code == 200:
        print("  ✅ ORDER PLACED! Your connection works fine.")
        try:
            order_id = r.json().get("order", {}).get("id")
            print(f"  Order ID: {order_id}")
        except:
            pass
    else:
        print(f"  ❌ REJECTED — reason above. Status {r.status_code}")

except Exception as e:
    print(f"  ❌ Error: {e}")

print()
print("=" * 50)
print("TEST COMPLETE — copy this output and share it")
print("=" * 50)
