# brokers/tradier.py — Tradier broker (sandbox + live)
# Handles SPY 0DTE options and equity orders

import requests
from datetime import datetime
import pytz
from .base import BaseBroker, OrderResult, AccountInfo, Position

ET = pytz.timezone("America/New_York")


class TradierBroker(BaseBroker):
    """
    Tradier brokerage — supports sandbox and live.
    Config keys:
        token:      API token
        account_id: account number
        sandbox:    True/False (default True)
    """

    def __init__(self, name: str, config: dict):
        super().__init__(name, "tradier", config)
        self.token = config.get("token", "")
        self.account_id = config.get("account_id", "")
        self.sandbox = config.get("sandbox", True)
        self.base_url = (
            "https://sandbox.tradier.com/v1"
            if self.sandbox
            else "https://api.tradier.com/v1"
        )
        self._headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        # Track open positions for closing
        self._open_positions = {}  # symbol -> occ_symbol

    def connect(self) -> bool:
        """Test connection by fetching profile."""
        if not self.token or not self.account_id:
            self._last_error = "Missing token or account_id"
            self._connected = False
            return False
        try:
            r = requests.get(
                f"{self.base_url}/user/profile",
                headers=self._headers, timeout=8
            )
            if r.status_code == 200:
                self._connected = True
                self._last_error = None
                return True
            else:
                self._last_error = f"HTTP {r.status_code}"
                self._connected = False
                return False
        except Exception as e:
            self._last_error = str(e)
            self._connected = False
            return False

    def get_account_info(self) -> AccountInfo:
        """Fetch balances and positions."""
        info = AccountInfo()
        if not self.token or not self.account_id:
            info.error = "Not configured"
            return info
        try:
            # Balances
            r = requests.get(
                f"{self.base_url}/accounts/{self.account_id}/balances",
                headers=self._headers, timeout=8
            )
            if r.status_code == 200:
                data = r.json().get("balances", {})
                info.equity = float(data.get("total_equity", 0))
                info.cash = float(
                    data.get("cash", {}).get("cash_available", 0)
                    or data.get("cash_available", 0) or 0
                )
                info.buying_power = float(
                    data.get("buying_power", 0) or 0
                )
                # Day P&L — may be nested
                info.day_pnl = float(
                    data.get("pnl", {}).get("day", 0)
                    or data.get("day_pnl", 0) or 0
                )
                info.connected = True

            # Positions
            r2 = requests.get(
                f"{self.base_url}/accounts/{self.account_id}/positions",
                headers=self._headers, timeout=8
            )
            if r2.status_code == 200:
                pos_data = r2.json().get("positions", {})
                if pos_data and pos_data != "null":
                    positions = pos_data.get("position", [])
                    if isinstance(positions, dict):
                        positions = [positions]
                    for p in positions:
                        info.positions.append(Position(
                            symbol=p.get("symbol", ""),
                            quantity=int(p.get("quantity", 0)),
                            side="long" if int(p.get("quantity", 0)) > 0 else "short",
                            entry_price=float(p.get("cost_basis", 0)),
                            current_price=float(p.get("last", 0) or 0),
                            pnl=float(p.get("unrealized_pnl", 0) or 0),
                        ))

        except Exception as e:
            info.error = str(e)

        return info

    def _get_spy_price(self) -> float:
        """Get current SPY price for strike selection."""
        try:
            r = requests.get(
                f"{self.base_url}/markets/quotes",
                headers=self._headers,
                params={"symbols": "SPY"}, timeout=5
            )
            return float(r.json()["quotes"]["quote"].get("last", 0))
        except:
            return 0.0

    def _build_occ_symbol(self, direction: str, strike: float,
                          expiration: str = None) -> str:
        """Build OCC option symbol for SPY."""
        if expiration is None:
            expiration = datetime.now(ET).strftime("%y%m%d")
        cp = "C" if direction == "UP" else "P"
        return f"SPY{expiration}{cp}{int(strike * 1000):08d}"

    def place_order(self, direction: str, symbol: str = "SPY",
                    quantity: int = 1, **kwargs) -> OrderResult:
        """
        Place a SPY 0DTE option order.
        direction: "UP" (buy call) or "DOWN" (buy put)
        """
        if not self.token or not self.account_id:
            return OrderResult(False, message="Not configured")

        try:
            # Get strike
            strike = kwargs.get("strike")
            if not strike:
                price = self._get_spy_price()
                if price <= 0:
                    return OrderResult(False, message="Can't get SPY price")
                strike = round(price)

            # Build option symbol
            expiration = kwargs.get("expiration")
            occ = self._build_occ_symbol(direction, strike, expiration)

            # Place order
            r = requests.post(
                f"{self.base_url}/accounts/{self.account_id}/orders",
                headers=self._headers,
                data={
                    "class": "option",
                    "symbol": symbol,
                    "option_symbol": occ,
                    "side": "buy_to_open",
                    "quantity": str(quantity),
                    "type": "market",
                    "duration": "day",
                },
                timeout=10,
            )

            resp = r.json()
            order_id = resp.get("order", {}).get("id")

            if r.status_code == 200 and order_id:
                self._open_positions[symbol] = occ
                return OrderResult(
                    True, order_id=str(order_id), symbol=occ,
                    message=f"Filled: {occ} x{quantity}"
                )
            else:
                return OrderResult(
                    False, message=f"HTTP {r.status_code}: {resp}"
                )

        except Exception as e:
            return OrderResult(False, message=str(e))

   def close_position(self, symbol: str = "SPY", **kwargs) -> OrderResult:
    occ = self._open_positions.get(symbol) or kwargs.get("occ_symbol")
    if not occ:
        return OrderResult(False, message="No open position to close")
    try:
        qty = kwargs.get("quantity", 1)
        r = requests.post(
            f"{self.base_url}/accounts/{self.account_id}/orders",
            headers=self._headers,
            data={
                "class": "option",
                "symbol": symbol,
                "option_symbol": occ,
                "side": "sell_to_close",
                "quantity": str(qty),
                "type": "market",
                "duration": "day",
            },
            timeout=10,
        )
        resp = r.json()
        order = resp.get("order", {})
        order_id = order.get("id")
        status = order.get("status", "")

        # Tradier returns 200 even on rejections — check the actual status
        if r.status_code == 200 and order_id and status != "rejected":
            # Don't pop yet — verify fill
            self._open_positions.pop(symbol, None)
            return OrderResult(True, order_id=str(order_id), message=str(resp))
        else:
            reason = resp.get("errors", resp)
            return OrderResult(False, message=f"Rejected: {reason}")
    except Exception as e:
        return OrderResult(False, message=str(e))
