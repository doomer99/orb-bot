# brokers/traderspost.py — Webhook broker (TradersPost → TopStep, prop firms)
# Sends JSON payloads to a webhook URL

import requests
from .base import BaseBroker, OrderResult, AccountInfo


class TradersPostBroker(BaseBroker):
    """
    Webhook-based broker for TradersPost, prop firms, etc.
    Config keys:
        webhook_url: the POST endpoint
        password:    webhook password
        ticker:      default ticker (e.g. "MES1!")
    """

    def __init__(self, name: str, config: dict):
        super().__init__(name, "webhook", config)
        self.webhook_url = config.get("webhook_url", "")
        self.password = config.get("password", "")
        self.ticker = config.get("ticker", "MES1!")

    def connect(self) -> bool:
        """Webhook brokers are 'connected' if URL is set."""
        if self.webhook_url:
            self._connected = True
            self._last_error = None
            return True
        else:
            self._connected = False
            self._last_error = "No webhook URL configured"
            return False

    def get_account_info(self) -> AccountInfo:
        """Webhook brokers don't expose account info."""
        return AccountInfo(
            connected=self._connected,
            error="Balance not available via webhook"
                  if self._connected else "Not connected"
        )

    def place_order(self, direction: str, symbol: str = None,
                    quantity: int = 1, **kwargs) -> OrderResult:
        """Send order via webhook."""
        if not self.webhook_url:
            return OrderResult(False, message="No webhook URL")

        ticker = symbol or self.ticker
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

        ticker = symbol or self.ticker
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
