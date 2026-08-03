# config.py — All environment variables and routing
import os

SIM_MODE = os.environ.get("SIM_MODE", "true").lower() == "true"
DAILY_LOSS_LIMIT = float(os.environ.get("DAILY_LOSS_LIMIT", "1000"))
DAILY_LOSS_BUFFER = float(os.environ.get("DAILY_LOSS_BUFFER", "200"))

BROKERS = {}

if os.environ.get("TRADIER_TOKEN") and os.environ.get("TRADIER_ACCOUNT"):
    BROKERS["tradier_sandbox"] = {
        "type": "tradier", "name": "Tradier Sandbox",
        "token": os.environ["TRADIER_TOKEN"],
        "account_id": os.environ["TRADIER_ACCOUNT"],
        "sandbox": os.environ.get("TRADIER_SANDBOX", "true").lower() == "true",
    }

if os.environ.get("TRADIER_LIVE_ACCOUNT"):
    BROKERS["tradier_live"] = {
        "type": "tradier", "name": "Tradier Live",
        "token": os.environ.get("TRADIER_LIVE_TOKEN", ""),
        "account_id": os.environ["TRADIER_LIVE_ACCOUNT"],
        "sandbox": False,
    }

if os.environ.get("P1_WEBHOOK_URL"):
    BROKERS["topstep"] = {
        "type": "webhook", "name": "TopStep (TradersPost)",
        "webhook_url": os.environ["P1_WEBHOOK_URL"],
        "password": os.environ.get("P1_PASSWORD", ""),
        "ticker": os.environ.get("P1_TICKER", "MES1!"),
    }

if os.environ.get("P3_WEBHOOK_URL"):
    BROKERS["prop_firm_2"] = {
        "type": "webhook", "name": "Prop Firm 2",
        "webhook_url": os.environ["P3_WEBHOOK_URL"],
        "password": os.environ.get("P3_PASSWORD", ""),
        "ticker": os.environ.get("P3_TICKER", "MES1!"),
    }

def _route(strategy_key, defaults):
    prefix = f"ROUTE_{strategy_key.upper()}"
    return {
        "broker": os.environ.get(f"{prefix}_BROKER", defaults.get("broker", "")),
        "enabled": os.environ.get(f"{prefix}_ENABLED", str(defaults.get("enabled", False))).lower() == "true",
        "symbol": os.environ.get(f"{prefix}_SYMBOL", defaults.get("symbol", "SPY")),
        "quantity": int(os.environ.get(f"{prefix}_QTY", defaults.get("quantity", 1))),
    }

ROUTES = {
    "Nour ML": _route("NOUR", {"broker": "tradier_sandbox", "enabled": True, "symbol": "SPY", "quantity": 1}),
}

DEFAULT_ROUTE = {"broker": "tradier_sandbox", "enabled": False, "symbol": "SPY", "quantity": 1}

def discover_strategies():
    import importlib, pkgutil, strategies
    from strategies.base import BaseStrategy
    found = []
    for importer, modname, ispkg in pkgutil.iter_modules(strategies.__path__):
        if modname == "base":
            continue
        try:
            mod = importlib.import_module(f"strategies.{modname}")
            for attr_name in dir(mod):
                attr = getattr(mod, attr_name)
                if isinstance(attr, type) and issubclass(attr, BaseStrategy) and attr is not BaseStrategy:
                    found.append(attr)
        except Exception as e:
            print(f"Could not load strategy '{modname}': {e}")
    return found
