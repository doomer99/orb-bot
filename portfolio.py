# portfolio.py — Portfolio manager with risk parity sizing
import json, os
from typing import Dict, List
import pytz

ET = pytz.timezone("America/New_York")
PORTFOLIO_FILE = "/tmp/portfolios.json"


class Portfolio:
    def __init__(self, name: str, config: dict = None):
        config = config or {}
        self.name = name
        self.broker_id: str = config.get("broker", "")
        self.risk_pct: float = config.get("risk_pct", 1.0)
        self.sizing_mode: str = config.get("sizing_mode", "risk_parity")
        self.strategy_names: List[str] = config.get("strategies", [])
        self.enabled: bool = config.get("enabled", True)
        self.max_daily_loss: float = config.get("max_daily_loss", 0)
        self.day_pnl: float = 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name, "broker": self.broker_id,
            "risk_pct": self.risk_pct, "sizing_mode": self.sizing_mode,
            "strategies": self.strategy_names, "enabled": self.enabled,
            "max_daily_loss": self.max_daily_loss,
        }

    def calculate_position_sizes(self, account_equity: float,
                                 asset_data: Dict[str, dict]) -> Dict[str, int]:
        if not asset_data or account_equity <= 0:
            return {sym: 1 for sym in asset_data}
        risk_budget = account_equity * (self.risk_pct / 100.0)
        n_assets = len(asset_data)
        if n_assets == 0:
            return {}
        sizes = {}
        if self.sizing_mode == "equal_contracts":
            per_asset = max(1, int(risk_budget / n_assets / 100))
            for sym in asset_data:
                sizes[sym] = max(1, per_asset)
        elif self.sizing_mode == "weighted":
            total_weight = sum(d.get("win_rate", 50) for d in asset_data.values()) or 1
            for sym, data in asset_data.items():
                weight = data.get("win_rate", 50) / total_weight
                dollar_alloc = risk_budget * weight
                expected_move = data["price"] * (data.get("avg_move_pct", 0.20) / 100.0) * data.get("point_value", 100)
                sizes[sym] = max(1, int(dollar_alloc / expected_move)) if expected_move > 0 else 1
        else:
            per_asset_risk = risk_budget / n_assets
            for sym, data in asset_data.items():
                expected_move = data["price"] * (data.get("avg_move_pct", 0.20) / 100.0) * data.get("point_value", 100)
                sizes[sym] = max(1, int(per_asset_risk / expected_move)) if expected_move > 0 else 1
        return sizes

    def get_daily_loss_limit(self, account_equity: float) -> float:
        return self.max_daily_loss if self.max_daily_loss > 0 else account_equity * (self.risk_pct / 100.0)

    def risk_ok(self, account_equity: float) -> bool:
        return abs(min(0, self.day_pnl)) < self.get_daily_loss_limit(account_equity)


class DirectAllocation:
    def __init__(self, name: str, config: dict = None):
        config = config or {}
        self.strategy_name: str = name
        self.broker_id: str = config.get("broker", "")
        self.symbol: str = config.get("symbol", "SPY")
        self.allocation_pct: float = config.get("allocation_pct", 100.0)
        self.quantity: int = config.get("quantity", 1)
        self.enabled: bool = config.get("enabled", True)

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy_name, "broker": self.broker_id,
            "symbol": self.symbol, "allocation_pct": self.allocation_pct,
            "quantity": self.quantity, "enabled": self.enabled,
        }

    def get_effective_quantity(self) -> int:
        return max(1, int(self.quantity * (self.allocation_pct / 100.0)))


def save_portfolios(portfolios: Dict[str, Portfolio], allocations: Dict[str, DirectAllocation]):
    data = {
        "portfolios": {n: p.to_dict() for n, p in portfolios.items()},
        "allocations": {n: a.to_dict() for n, a in allocations.items()},
    }
    try:
        with open(PORTFOLIO_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def load_portfolios() -> tuple:
    portfolios, allocations = {}, {}
    if os.path.exists(PORTFOLIO_FILE):
        try:
            with open(PORTFOLIO_FILE, "r") as f:
                data = json.load(f)
            for name, cfg in data.get("portfolios", {}).items():
                portfolios[name] = Portfolio(name, cfg)
            for name, cfg in data.get("allocations", {}).items():
                allocations[name] = DirectAllocation(name, cfg)
        except Exception:
            pass
    return portfolios, allocations


DEFAULT_ASSET_DATA = {
    "SPY": {"price": 757.0, "avg_move_pct": 0.19, "point_value": 100},
    "QQQ": {"price": 520.0, "avg_move_pct": 0.29, "point_value": 100},
    "TSLA": {"price": 260.0, "avg_move_pct": 1.17, "point_value": 100},
    "NVDA": {"price": 140.0, "avg_move_pct": 0.89, "point_value": 100},
    "AAPL": {"price": 230.0, "avg_move_pct": 0.61, "point_value": 100},
    "AMZN": {"price": 200.0, "avg_move_pct": 0.69, "point_value": 100},
    "GOOGL": {"price": 180.0, "avg_move_pct": 0.70, "point_value": 100},
    "META": {"price": 500.0, "avg_move_pct": 0.72, "point_value": 100},
    "MSFT": {"price": 450.0, "avg_move_pct": 0.53, "point_value": 100},
    "GLD": {"price": 230.0, "avg_move_pct": 0.35, "point_value": 100},
    "MES1!": {"price": 5570.0, "avg_move_pct": 0.19, "point_value": 5},
    "MNQ1!": {"price": 19800.0, "avg_move_pct": 0.29, "point_value": 2},
}


def get_asset_data(symbols: List[str], live_prices: Dict[str, float] = None) -> Dict[str, dict]:
    result = {}
    for sym in symbols:
        base = DEFAULT_ASSET_DATA.get(sym, {"price": 100.0, "avg_move_pct": 0.50, "point_value": 100}).copy()
        if live_prices and sym in live_prices:
            base["price"] = live_prices[sym]
        result[sym] = base
    return result
