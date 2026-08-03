# fire_full_system.py — End-to-end test through Router → Broker
# Tests the EXACT same code path as a real signal

import os
import sys
sys.path.insert(0, "/app" if os.path.exists("/app") else ".")

from datetime import datetime
import pytz
from router import Router
from strategies.nour import NourStrategy
from strategies.base import Signal

ET = pytz.timezone("America/New_York")

print("=" * 55)
print("FULL SYSTEM TEST — Router → Broker")
print("=" * 55)

# 1. Create router (same as dashboard.py does)
print("\n1. Creating router...")
router = Router()

# 2. Init brokers
print("\n2. Initializing brokers...")
router.init_brokers()
print(f"   Brokers loaded: {list(router.brokers.keys())}")

if not router.brokers:
    print("   ❌ No brokers configured — check Railway env vars")
    sys.exit(1)

# 3. Register Nour ML strategy
print("\n3. Registering Nour ML strategy...")
nour = NourStrategy()
router.register_strategy(nour)
print(f"   Route: {router.routes.get('Nour ML', {})}")

# 4. Create a fake signal (same format check_signal returns)
print("\n4. Creating test signal...")
signal = Signal(
    direction="UP",
    confidence=0.801,
    symbol="SPY",
    quantity=1,
    entry_time=datetime.now(ET).strftime("%H:%M:%S"),
    exit_minutes=15,
    metadata={"prob_up": 0.801, "model": "TEST"},
)
print(f"   Signal: {signal.direction} ({signal.confidence:.1%})")

# 5. Fire through router.place_order — THE REAL TEST
print("\n5. Firing order through router.place_order()...")
print("   (This is the exact code path that failed this morning)")
print()

success = router.place_order("Nour ML", signal)

print()
if success:
    print("✅ ORDER PLACED SUCCESSFULLY!")
    print("   Your system works end-to-end.")
    
    # Try closing too
    print("\n6. Closing position through router.close_order()...")
    closed = router.close_order("Nour ML")
    if closed:
        print("   ✅ Position closed!")
    else:
        print("   ⚠️ Close didn't work — check logs above")
else:
    print("❌ ORDER FAILED — check the log lines above for the reason")

print()
print("=" * 55)
print("Router log:")
print("=" * 55)
for line in router.log_lines:
    print(f"  {line}")
print("=" * 55)
print("DONE")
