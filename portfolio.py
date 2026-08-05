# portfolio.py — Portfolio: one broker + one strategy + risk settings
# This is the primary trading unit. Each portfolio fires independently.
import json, os
from typing import Dict, List, Optional
from config import DATA_DIR

PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolios.json")


class Portfolio:
    """
    One portfolio = one broker + one strategy + one symbol + risk config.
    The router iterates portfolios, not strategies.
    """

    def __init__(self, name: str, config: dict = None):
        config = config or {}
        self.name = name
        self.broker_id: str = config.get("broker", "")
        self.strategy_name: str = config.get("strategy", "")
        self.symbol: str = config.get("symbol", "SPY")
        self.quantity: int = config.get("quantity", 1)
        self.risk_pct: float = config.get("risk_pct", 1.0)
        self.max_daily_loss: float = config.get("max_daily_loss", 0)
        self.enabled: bool = config.get("enabled", True)

        # Runtime state (not persisted)
        self.today_traded: bool = False
        self.day_pnl: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "broker": self.broker_id,
            "strategy": self.strategy_name,
            "symbol": self.symbol,
            "quantity": self.quantity,
            "risk_pct": self.risk_pct,
            "max_daily_loss": self.max_daily_loss,
            "enabled": self.enabled,
        }

    def calculate_quantity(self, equity: float, asset_data: dict) -> int:
        """
        Size the position from equity and risk_pct.
        Returns number of contracts/shares.
        """
        if equity <= 0:
            return self.quantity  # fallback to static

        risk_budget = equity * (self.risk_pct / 100.0)
        data = asset_data.get(self.symbol, {})
        price = data.get("price", 100)
        point_value = data.get("point_value", 100)
        avg_move = data.get("avg_move_pct", 0.20)

        # Expected dollar risk per contract
        expected_move = price * (avg_move / 100.0) * point_value
        if expected_move > 0:
            return max(1, int(risk_budget / expected_move))
        return self.quantity

    def get_daily_loss_limit(self, equity: float) -> float:
        if self.max_daily_loss > 0:
            return self.max_daily_loss
        return equity * (self.risk_pct / 100.0) if equity > 0 else 500.0

    def risk_ok(self, equity: float) -> bool:
        return abs(min(0, self.day_pnl)) < self.get_daily_loss_limit(equity)

    def reset_daily(self):
        self.today_traded = False
        self.day_pnl = 0.0


# ── Asset data for sizing ──

DEFAULT_ASSET_DATA = {
    "SPY": {"price": 757.0, "avg_move_pct": 0.19, "point_value": 100},
    "QQQ": {"price": 520.0, "avg_move_pct": 0.29, "point_value": 100},
    "MES": {"price": 5570.0, "avg_move_pct": 0.19, "point_value": 5},
    "MES1!": {"price": 5570.0, "avg_move_pct": 0.19, "point_value": 5},
    "MNQ": {"price": 19800.0, "avg_move_pct": 0.29, "point_value": 2},
    "MNQ1!": {"price": 19800.0, "avg_move_pct": 0.29, "point_value": 2},
    "TSLA": {"price": 260.0, "avg_move_pct": 1.17, "point_value": 100},
    "NVDA": {"price": 140.0, "avg_move_pct": 0.89, "point_value": 100},
    "AAPL": {"price": 230.0, "avg_move_pct": 0.61, "point_value": 100},
    "AMZN": {"price": 200.0, "avg_move_pct": 0.69, "point_value": 100},
    "GOOGL": {"price": 180.0, "avg_move_pct": 0.70, "point_value": 100},
    "META": {"price": 500.0, "avg_move_pct": 0.72, "point_value": 100},
    "MSFT": {"price": 450.0, "avg_move_pct": 0.53, "point_value": 100},
    "GLD": {"price": 230.0, "avg_move_pct": 0.35, "point_value": 100},
}


def get_asset_data(symbols: List[str]) -> Dict[str, dict]:
    result = {}
    for sym in symbols:
        base = DEFAULT_ASSET_DATA.get(
            sym, {"price": 100.0, "avg_move_pct": 0.50, "point_value": 100}
        ).copy()
        result[sym] = base
    return result


# ── Persistence ──

def save_portfolios(portfolios: Dict[str, Portfolio]):
    data = {name: p.to_dict() for name, p in portfolios.items()}
    try:
        os.makedirs(os.path.dirname(PORTFOLIO_FILE) or ".", exist_ok=True)
        with open(PORTFOLIO_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Could not save portfolios: {e}")


def load_portfolios() -> Dict[str, Portfolio]:
    portfolios = {}
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r") as f:
                data = json.load(f)
            for name, cfg in data.items():
                portfolios[name] = Portfolio(name, cfg)
        except Exception as e:
            print(f"Could not load portfolios: {e}")
    return portfolios
