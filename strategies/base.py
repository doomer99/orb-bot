# strategies/base.py — Abstract strategy interface
# Every strategy implements these methods. Add a strategy = add one file.

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict
from datetime import datetime, time


@dataclass
class Signal:
    """What a strategy returns when it fires."""
    direction: str              # "UP" or "DOWN"
    confidence: float           # 0.0 - 1.0
    symbol: str = "SPY"         # what to trade
    quantity: int = 1
    entry_time: Optional[str] = None
    exit_time: Optional[str] = None
    exit_minutes: int = 15      # hold for N minutes
    stop_loss_pct: float = 0.0  # 0 = no stop
    take_profit_pct: float = 0.0  # 0 = no TP
    metadata: Dict = field(default_factory=dict)  # strategy-specific info


class BaseStrategy(ABC):
    """Every strategy must implement these."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self.enabled = True
        self._trained = False
        self._last_signal = None
        self._today_traded = False
        self._trade_log = []      # list of dicts for history

    @abstractmethod
    def initialize(self) -> bool:
        """
        One-time setup — load model, pull history, etc.
        Called at startup and midnight retrain.
        Returns True if ready to trade.
        """
        pass

    @abstractmethod
    def check_signal(self, current_time: datetime) -> Optional[Signal]:
        """
        Check if the strategy wants to trade right now.
        Called every tick during the trading window.
        Returns Signal or None.
        """
        pass

    @abstractmethod
    def should_exit(self, current_time: datetime,
                    entry_price: float, current_price: float,
                    direction: str) -> bool:
        """
        Check if an open trade should be closed.
        Called every tick while in a trade.
        """
        pass

    def get_trading_window(self) -> tuple:
        """
        Return (start_time, end_time) as time objects.
        The router only calls check_signal during this window.
        """
        return (time(9, 30), time(10, 0))

    def reset_daily(self):
        """Called at midnight to reset for the new day."""
        self._today_traded = False
        self._last_signal = None

    @property
    def is_ready(self) -> bool:
        return self._trained and self.enabled

    def record_trade(self, signal: Signal, result: str,
                     pnl_pct: float = 0.0):
        """Log a completed trade."""
        self._trade_log.append({
            "date": datetime.now().strftime("%Y-%m-%d"),
            "direction": signal.direction,
            "confidence": signal.confidence,
            "result": result,
            "pnl_pct": pnl_pct,
        })
        # Keep last 100
        self._trade_log = self._trade_log[-100:]

    def get_stats(self) -> dict:
        """Return win rate, total trades, recent performance."""
        trades = self._trade_log
        if not trades:
            return {"total": 0, "win_rate": 0, "recent_pnl": 0}

        wins = sum(1 for t in trades if t["result"] == "WIN")
        total = len(trades)
        recent = trades[-20:]
        recent_pnl = sum(t.get("pnl_pct", 0) for t in recent)

        return {
            "total": total,
            "wins": wins,
            "win_rate": round(wins / total * 100, 1) if total > 0 else 0,
            "recent_pnl": round(recent_pnl, 2),
            "last_5": trades[-5:],
        }

    def to_dict(self) -> dict:
        """Serialize for dashboard."""
        stats = self.get_stats()
        return {
            "name": self.name,
            "description": self.description,
            "enabled": self.enabled,
            "ready": self.is_ready,
            "today_traded": self._today_traded,
            "last_signal": self._last_signal.__dict__ if self._last_signal else None,
            "stats": stats,
        }
