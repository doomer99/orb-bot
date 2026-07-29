# config.py — All environment variables and strategy-to-broker routing
# Everything reads from Railway env vars. No secrets in code.

import os


# ══════════════════════════════════════════════════════════════
#  GLOBAL
# ══════════════════════════════════════════════════════════════
SIM_MODE = os.environ.get("SIM_MODE", "true").lower() == "true"
DAILY_LOSS_LIMIT = float(os.environ.get("DAILY_LOSS_LIMIT", "1000"))
DAILY_LOSS_BUFFER = float(os.environ.get("DAILY_LOSS_BUFFER", "200"))


# ══════════════════════════════════════════════════════════════
#  BROKER CONFIGS
#  Each broker gets a dict. Add new brokers here.
#  The key is the broker ID used in ROUTES below.
# ══════════════════════════════════════════════════════════════
BROKERS = {}

# Tradier Sandbox
if os.environ.get("TRADIER_TOKEN") and os.environ.get("TRADIER_ACCOUNT"):
    BROKERS["tradier_sandbox"] = {
        "type": "tradier",
        "name": "Tradier Sandbox",
        "token": os.environ["TRADIER_TOKEN"],
        "account_id": os.environ["TRADIER_ACCOUNT"],
        "sandbox": os.environ.get("TRADIER_SANDBOX", "true").lower() == "true",
    }

# Tradier Live
if os.environ.get("TRADIER_LIVE_ACCOUNT"):
    BROKERS["tradier_live"] = {
        "type": "tradier",
        "name": "Tradier Live",
        "token": os.environ.get("TRADIER_LIVE_TOKEN", ""),
        "account_id": os.environ["TRADIER_LIVE_ACCOUNT"],
        "sandbox": False,
    }

# TopStep via TradersPost (P1)
if os.environ.get("P1_WEBHOOK_URL"):
    BROKERS["topstep"] = {
        "type": "webhook",
        "name": "TopStep (TradersPost)",
        "webhook_url": os.environ["P1_WEBHOOK_URL"],
        "password": os.environ.get("P1_PASSWORD", ""),
        "ticker": os.environ.get("P1_TICKER", "MES1!"),
    }

# Prop Firm 2 via TradersPost (P3)
if os.environ.get("P3_WEBHOOK_URL"):
    BROKERS["prop_firm_2"] = {
        "type": "webhook",
        "name": "Prop Firm 2",
        "webhook_url": os.environ["P3_WEBHOOK_URL"],
        "password": os.environ.get("P3_PASSWORD", ""),
        "ticker": os.environ.get("P3_TICKER", "MES1!"),
    }


# ══════════════════════════════════════════════════════════════
#  STRATEGY → BROKER ROUTING
#  Maps strategy names to broker IDs + trade parameters.
#  Set via env vars or defaults below.
#  Format: ROUTE_<STRATEGY>_<FIELD>
#
#  Example Railway vars:
#    ROUTE_NOUR_BROKER=tradier_sandbox
#    ROUTE_NOUR_ENABLED=true
#    ROUTE_NOUR_QTY=1
#    ROUTE_NOUR_SYMBOL=SPY
# ══════════════════════════════════════════════════════════════

def _route(strategy_key, defaults):
    """Build a route config from env vars with fallbacks."""
    prefix = f"ROUTE_{strategy_key.upper()}"
    return {
        "broker": os.environ.get(f"{prefix}_BROKER", defaults.get("broker", "")),
        "enabled": os.environ.get(
            f"{prefix}_ENABLED", str(defaults.get("enabled", False))
        ).lower() == "true",
        "symbol": os.environ.get(f"{prefix}_SYMBOL", defaults.get("symbol", "SPY")),
        "quantity": int(os.environ.get(f"{prefix}_QTY", defaults.get("quantity", 1))),
    }


ROUTES = {
    "Nour ML": _route("NOUR", {
        "broker": "tradier_sandbox",
        "enabled": True,
        "symbol": "SPY",
        "quantity": 1,
    }),
    # Future strategies — add routing here
    # "Stochastic 15m+5m": _route("STOCHASTIC", {
    #     "broker": "tradier_sandbox",
    #     "enabled": False,
    #     "symbol": "SPY",
    #     "quantity": 1,
    # }),
    # "Trend Flip": _route("TREND_FLIP", {
    #     "broker": "topstep",
    #     "enabled": False,
    #     "symbol": "MES1!",
    #     "quantity": 1,
    # }),
}
