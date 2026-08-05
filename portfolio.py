# config.py — All environment variables and broker definitions
import os

SIM_MODE = os.environ.get("SIM_MODE", "true").lower() == "true"
DAILY_LOSS_LIMIT = float(os.environ.get("DAILY_LOSS_LIMIT", "1000"))
DAILY_LOSS_BUFFER = float(os.environ.get("DAILY_LOSS_BUFFER", "200"))

# ── Persistence path (survives Railway redeploys if on a volume) ──
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))

# ── Broker definitions (from env vars) ──
BROKERS = {}

if os.environ.get("TRADIER_TOKEN") and os.environ.get("TRADIER_ACCOUNT"):
    BROKERS["tradier_sandbox"] = {
        "type": "tradier", "name": "Tradier Sandbox",
        "token": os.environ["TRADIER_TOKEN"],
        "account_id": os.environ["TRADIER_ACCOUNT"],
        "sandbox": os.environ.get("TRADIER_SANDBOX", "true").lower() == "true",
    }

if os.environ.get("TRADIER_LIVE_TOKEN") and os.environ.get("TRADIER_LIVE_ACCOUNT"):
    BROKERS["tradier_live"] = {
        "type": "tradier", "name": "Tradier Live",
        "token": os.environ["TRADIER_LIVE_TOKEN"],
        "account_id": os.environ["TRADIER_LIVE_ACCOUNT"],
        "sandbox": False,
    }

if os.environ.get("P1_WEBHOOK_URL"):
    BROKERS["topstep"] = {
        "type": "webhook", "name": "TopStep (TradersPost)",
        "webhook_url": os.environ["P1_WEBHOOK_URL"],
        "password": os.environ.get("P1_PASSWORD", ""),
        "ticker": os.environ.get("P1_TICKER", "MES"),
        "asset_class": os.environ.get("P1_ASSET_CLASS", "futures"),
    }

if os.environ.get("P2_WEBHOOK_URL"):
    BROKERS["prop_firm_2"] = {
        "type": "webhook", "name": "Prop Firm 2",
        "webhook_url": os.environ["P2_WEBHOOK_URL"],
        "password": os.environ.get("P2_PASSWORD", ""),
        "ticker": os.environ.get("P2_TICKER", "MES"),
        "asset_class": os.environ.get("P2_ASSET_CLASS", "futures"),
    }

if os.environ.get("P3_WEBHOOK_URL"):
    BROKERS["prop_firm_3"] = {
        "type": "webhook", "name": "Prop Firm 3",
        "webhook_url": os.environ["P3_WEBHOOK_URL"],
        "password": os.environ.get("P3_PASSWORD", ""),
        "ticker": os.environ.get("P3_TICKER", "MES"),
        "asset_class": os.environ.get("P3_ASSET_CLASS", "futures"),
    }


def discover_strategies():
    """Auto-discover all strategy classes in the strategies/ package."""
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
