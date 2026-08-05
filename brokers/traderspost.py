# brokers/traderspost.py — Webhook broker (TradersPost → TopStep, prop firms)
# Sends JSON payloads to a webhook URL

import os
import requests
from .base import BaseBroker, OrderResult, AccountInfo

# Map equity/ETF symbols to their futures equivalents
SYMBOL_MAP = {
    # S&P 500
    "SPY": "MES",
    "ES": "ES",
    "MES": "MES",
    "MES1!": "MES",
    # Nasdaq
    "QQQ": "MNQ",
    "NQ": "NQ",
    "MNQ": "MNQ",
    "MNQ1!": "MNQ",
    # Gold
    "GLD": "MGC",
    "GC": "GC",
    "MGC": "MGC",
    # Crude Oil
    "USO": "MCL",
    "CL": "CL",
    "MCL": "MCL",
    # Russell 2000
    "IWM": "M2K",
    "RTY": "RTY",
    "M2K": "M2K",
    # Dow
    "DIA": "MYM",
    "YM": "YM",
    "MYM": "MYM",
    # Bonds
    "TLT": "ZN",
    "ZN": "ZN",
    # Individual stocks — pass through as-is for brokers that support them
    "TSLA": "TSLA",
    "AAPL": "AAPL",
    "NVDA": "NVDA",
    "AMD": "AMD",
    "AMZN": "AMZN",
    "META": "META",
    "MSFT": "MSFT",
    "GOOGL": "GOOGL",
}


class TradersPostBroker(BaseBroker):
    """
    Webhook-based broker for TradersPost, prop firms, etc.
    Config keys:
        webhook_url:  the POST endpoint
        password:     webhook password
        ticker:       default ticker (e.g. "MES")
        asset_class:  "futures", "options", or "equity" — controls symbol translation
    """

    def __init__(self, name: str, config: dict):
        super().__init__(name, "webhook", config)
        self.webhook_url = config.get("webhook_url", "")
        self.password = config.get("password", "")
        self.ticker = config.get("ticker", "MES")
        self.asset_class = config.get("asset_class", "futures")  # futures, options, equity

        # Optional: manual balance for display (TradersPost has no balance API)
        # Set P1_BALANCE=101000 in env to show $101k on dashboard
        self._manual_balance = float(os.environ.get("P1_BALANCE", "0"))

        # Connection health tracking
        self._last_ping_ok = False
        self._last_ping_error = None

    def _map_symbol(self, symbol: str) -> str:
        """Translate symbols based on asset_class setting."""
        if not symbol:
            return self.ticker
        if self.asset_class == "futures":
            mapped = SYMBOL_MAP.get(symbol.upper())
            return mapped if mapped else symbol
        # For options and equity, pass through as-is
        return symbol

    def connect(self) -> bool:
        """
        Webhook brokers are 'connected' if URL is set.
        Also does a lightweight check that the URL is reachable.
        """
        if not self.webhook_url:
            self._connected = False
            self._last_error = "No webhook URL configured"
            return False

        # Verify the webhook endpoint is reachable with a HEAD/GET check
        try:
            # TradersPost webhooks respond to GET with a simple page
            # We just check DNS + TLS resolve, not a full trade
            r = requests.head(self.webhook_url, timeout=5, allow_redirects=True)
            # Any response (even 405 Method Not Allowed) means the endpoint exists
            self._connected = True
            self._last_ping_ok = True
            self._last_error = None
            self._last_ping_error = None
            return True
        except requests.exceptions.ConnectionError:
            # URL exists but endpoint down — still mark as configured
            self._connected = True
            self._last_ping_ok = False
            self._last_ping_error = "Endpoint unreachable"
            self._last_error = None
            return True
        except Exception as e:
            # URL is set, so technically configured
            self._connected = True
            self._last_ping_ok = False
            self._last_ping_error = str(e)
            self._last_error = None
            return True

    def get_account_info(self) -> AccountInfo:
        """
        Webhook brokers don't expose account info via API.
        TradersPost has no public account API yet.

        If P1_BALANCE is set in env, we display that as equity.
        Otherwise, we return connected=True with zero equity
        (dashboard will show 'ON' instead of a dollar amount).
        """
        if not self._connected:
            return AccountInfo(connected=False, error="Not connected")

        return AccountInfo(
            connected=True,
            equity=self._manual_balance,
            error=self._last_ping_error,
        )

    def place_order(self, direction: str, symbol: str = None,
                    quantity: int = 1, **kwargs) -> OrderResult:
        """Send order via webhook."""
        if not self.webhook_url:
            return OrderResult(False, message="No webhook URL")

        ticker = self._map_symbol(symbol)
        action = "buy" if direction == "UP" else "sell"

        payload = {
            "password": self.password,
            "ticker": ticker,
            "action": action,
            "quantity": quantity,
        }

        # Add option fields if present
        if kwargs.get("option_type"):
            payload["option_type"] = kwargs["option_type"]
        if kwargs.get("expiration"):
            payload["expiration"] = kwargs["expiration"]

        try:
            r = requests.post(self.webhook_url, json=payload, timeout=10)
            ok = r.status_code == 200
            return OrderResult(
                ok,
                message=f"HTTP {r.status_code}"
                        + (f": {r.text[:200]}" if not ok else "")
            )
        except Exception as e:
            return OrderResult(False, message=str(e))

    def close_position(self, symbol: str = None, **kwargs) -> OrderResult:
        """Send close via webhook."""
        if not self.webhook_url:
            return OrderResult(False, message="No webhook URL")

        ticker = self._map_symbol(symbol)
        direction = kwargs.get("direction", "UP")
        action = "sell" if direction == "UP" else "buy"
        quantity = kwargs.get("quantity", 1)

        payload = {
            "password": self.password,
            "ticker": ticker,
            "action": action,
            "quantity": quantity,
            "closePosition": True,
        }

        try:
            r = requests.post(self.webhook_url, json=payload, timeout=10)
            ok = r.status_code == 200
            return OrderResult(ok, message=f"HTTP {r.status_code}")
        except Exception as e:
            return OrderResult(False, message=str(e))
