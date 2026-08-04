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

    def _safe_json(self, r):
        """Parse JSON safely — returns (dict, error_string)."""
        if not r.text.strip():
            return None, f"HTTP {r.status_code}: empty response"
        try:
            return r.json(), None
        except Exception:
            return None, f"HTTP {r.status_code}: {r.text[:200]}"

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
            data, err = self._safe_json(r)
            if data and r.status_code == 200:
                bal = data.get("balances", {})
                info.equity = float(bal.get("total_equity", 0))
                info.cash = float(
                    bal.get("cash", {}).get("cash_available", 0)
                    or bal.get("cash_available", 0) or 0
                )
                info.buying_power = float(
                    bal.get("buying_power", 0) or 0
                )
                info.day_pnl = float(
                    bal.get("pnl", {}).get("day", 0)
                    or bal.get("day_pnl", 0) or 0
                )
                info.connected = True

            # Positions
            r2 = requests.get(
                f"{self.base_url}/accounts/{self.account_id}/positions",
                headers=self._headers, timeout=8
            )
            data2, err2 = self._safe_json(r2)
            if data2 and r2.status_code == 200:
                pos_data = data2.get("positions", {})
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
            data, err = self._safe_json(r)
            if not data:
                return 0.0
            return float(data["quotes"]["quote"].get("last", 0))
        except:
            return 0.0

    def _build_occ_symbol(self, direction: str, strike: float,
                          expiration: str = None) -> str:
        """Build OCC option symbol for SPY."""
        if expiration is None:
            expiration = datetime.now(ET).strftime("%y%m%d")
        cp = "C" if direction == "UP" else "P"
        return f"SPY{expiration}{cp}{int(strike * 1000):08d}"

    # ── Premium safety limits ──
    MAX_PREMIUM = 3.50        # Don't pay more than $3.50 per contract
    MAX_SPREAD_PCT = 0.30     # Don't buy if bid-ask spread is > 30% of ask
    MIN_BID = 0.05            # Don't buy options with no bid (illiquid)

    def _get_option_quote(self, occ_symbol: str) -> dict:
        """Get bid/ask/last for an option."""
        try:
            r = requests.get(
                f"{self.base_url}/markets/quotes",
                headers=self._headers,
                params={"symbols": occ_symbol, "greeks": "false"},
                timeout=5
            )
            data, err = self._safe_json(r)
            if not data:
                return {}
            quote = data.get("quotes", {}).get("quote", {})
            if isinstance(quote, list):
                quote = quote[0] if quote else {}
            return quote
        except Exception:
            return {}

    def _check_premium(self, occ_symbol: str) -> tuple:
        """
        Check if option premium is reasonable.
        Returns (ok: bool, reason: str, quote: dict)
        """
        quote = self._get_option_quote(occ_symbol)
        if not quote:
            # Can't get quote — proceed with caution but don't block
            return True, "No quote available — proceeding", {}

        bid = float(quote.get("bid", 0) or 0)
        ask = float(quote.get("ask", 0) or 0)
        last = float(quote.get("last", 0) or 0)

        # Check if option is liquid enough
        if bid < self.MIN_BID:
            return False, f"No bid ({bid}) — option may be illiquid or worthless", quote

        # Check premium isn't too high
        price = ask if ask > 0 else last
        if price > self.MAX_PREMIUM:
            return False, f"Premium too high (${price:.2f} > ${self.MAX_PREMIUM:.2f} limit)", quote

        # Check bid-ask spread isn't too wide
        if ask > 0 and bid > 0:
            spread = (ask - bid) / ask
            if spread > self.MAX_SPREAD_PCT:
                return False, f"Spread too wide ({spread:.0%}) — bid ${bid:.2f} / ask ${ask:.2f}", quote

        return True, f"Premium OK — bid ${bid:.2f} / ask ${ask:.2f}", quote

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

            # ── Premium sanity check ──
            skip_check = kwargs.get("skip_premium_check", False)
            if not skip_check:
                ok, reason, quote = self._check_premium(occ)
                if not ok:
                    return OrderResult(False, message=f"BLOCKED: {reason} [{occ}]")
                print(f"Premium check [{occ}]: {reason}")

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

            # Safe JSON parse
            resp, err = self._safe_json(r)
            if not resp:
                return OrderResult(False, message=err)

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
        """Close the open option position. Checks actual account positions first."""
        occ = self._open_positions.get(symbol) or kwargs.get("occ_symbol")

        # If we don't have the OCC symbol in memory, look it up from the account
        if not occ:
            occ = self._find_open_position(symbol)

        if not occ:
            return OrderResult(False, message=f"No open position found for {symbol}")

        # Verify the position actually exists before trying to close
        actual_qty = self._get_position_quantity(occ)
        if actual_qty <= 0:
            # Position doesn't exist — maybe already closed
            self._open_positions.pop(symbol, None)
            return OrderResult(False, message=f"Position {occ} not found in account (may already be closed)")

        try:
            qty = kwargs.get("quantity", 1)
            # Use actual quantity if less than requested
            if actual_qty < qty:
                qty = actual_qty

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

            # Safe JSON parse
            resp, err = self._safe_json(r)
            if not resp:
                return OrderResult(False, message=err)

            order = resp.get("order", {})
            order_id = order.get("id")
            status = order.get("status", "")
            if r.status_code == 200 and order_id and status != "rejected":
                self._open_positions.pop(symbol, None)
                return OrderResult(True, order_id=str(order_id), message=str(resp))
            else:
                reason = resp.get("errors", resp)
                return OrderResult(False, message=f"Rejected: {reason}")
        except Exception as e:
            return OrderResult(False, message=str(e))

    def _find_open_position(self, underlying: str = "SPY") -> str:
        """Look up actual open positions in Tradier account for this underlying."""
        try:
            r = requests.get(
                f"{self.base_url}/accounts/{self.account_id}/positions",
                headers=self._headers, timeout=8
            )
            data, err = self._safe_json(r)
            if not data or r.status_code != 200:
                return ""
            pos_data = data.get("positions", {})
            if not pos_data or pos_data == "null":
                return ""
            positions = pos_data.get("position", [])
            if isinstance(positions, dict):
                positions = [positions]
            for p in positions:
                sym = p.get("symbol", "")
                qty = int(p.get("quantity", 0))
                # Match option positions for this underlying (e.g., SPY240805C00550000)
                if sym.startswith(underlying) and qty > 0:
                    # Cache it for future use
                    self._open_positions[underlying] = sym
                    return sym
            return ""
        except Exception:
            return ""

    def _get_position_quantity(self, occ_symbol: str) -> int:
        """Check if a specific position actually exists and return its quantity."""
        try:
            r = requests.get(
                f"{self.base_url}/accounts/{self.account_id}/positions",
                headers=self._headers, timeout=8
            )
            data, err = self._safe_json(r)
            if not data or r.status_code != 200:
                return 0
            pos_data = data.get("positions", {})
            if not pos_data or pos_data == "null":
                return 0
            positions = pos_data.get("position", [])
            if isinstance(positions, dict):
                positions = [positions]
            for p in positions:
                if p.get("symbol", "") == occ_symbol:
                    return int(p.get("quantity", 0))
            return 0
        except Exception:
            return 0
