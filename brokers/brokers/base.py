# brokers/base.py — Abstract broker interface
# Every broker implements these methods. Add a new broker = add one file.

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime


@dataclass
class OrderResult:
    success: bool
    order_id: Optional[str] = None
    symbol: Optional[str] = None
    message: str = ""


@dataclass
class Position:
    symbol: str
    quantity: int
    side: str           # "long" / "short"
    entry_price: float
    current_price: float = 0.0
    pnl: float = 0.0
    option_symbol: Optional[str] = None


@dataclass
class AccountInfo:
    equity: float = 0.0
    cash: float = 0.0
    day_pnl: float = 0.0
    buying_power: float = 0.0
    positions: List[Position] = field(default_factory=list)
    connected: bool = False
    error: Optional[str] = None


class BaseBroker(ABC):
    """Every broker must implement these methods."""

    def __init__(self, name: str, broker_type: str, config: dict):
        self.name = name
        self.broker_type = broker_type
        self.config = config
        self._connected = False
        self._last_error = None

    @abstractmethod
    def connect(self) -> bool:
        """Test the connection. Returns True if credentials work."""
        pass

    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """Fetch balances, positions, day P&L."""
        pass

    @abstractmethod
    def place_order(self, direction: str, symbol: str,
                    quantity: int, **kwargs) -> OrderResult:
        """
        Place an order.
        direction: "UP" or "DOWN"
        symbol: "SPY", "MES1!", etc.
        quantity: number of contracts/shares
        kwargs: option_type, expiration, strike, etc.
        """
        pass

    @abstractmethod
    def close_position(self, symbol: str, **kwargs) -> OrderResult:
        """Close an open position."""
        pass

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def to_dict(self) -> dict:
        """Serialize for dashboard display."""
        return {
            "name": self.name,
            "type": self.broker_type,
            "connected": self._connected,
            "error": self._last_error,
        }
