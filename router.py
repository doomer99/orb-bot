# router.py — Strategy orchestrator with portfolios + circuit breaker
import time, threading, pytz, json, os
from datetime import datetime, date
from typing import Dict, List, Optional
from brokers import TradierBroker, TradersPostBroker
from brokers.base import BaseBroker
from strategies.base import BaseStrategy, Signal
from config import BROKERS, ROUTES, SIM_MODE, DAILY_LOSS_LIMIT, DAILY_LOSS_BUFFER
try:
    from config import PROP_ALLOCATIONS
except ImportError:
    PROP_ALLOCATIONS = {}
from portfolio import Portfolio, DirectAllocation, load_portfolios, save_portfolios, get_asset_data

ET = pytz.timezone("America/New_York")

TRADES_FILE = os.path.join(os.path.dirname(__file__), "active_trades.json")


class Router:
    def __init__(self):
        self.brokers: Dict[str, BaseBroker] = {}
        self.strategies: Dict[str, BaseStrategy] = {}
        self.routes: Dict[str, dict] = {}
        self.active_trades: Dict[str, dict] = {}
        self.log_lines: List[str] = []
        self.day_pnl: float = 0.0
        self._running = False
        self.portfolios: Dict[str, Portfolio] = {}
        self.allocations: Dict[str, DirectAllocation] = {}
        self._load_portfolio_config()
        self._load_prop_allocations()
        self._load_active_trades()
        self._circuit_breaker_active = False
        self._circuit_breaker_time = None

    def _load_prop_allocations(self):
        """Load prop firm allocations from config (env-driven)."""
        for name, cfg in PROP_ALLOCATIONS.items():
            if name not in self.allocations:
                self.allocations[name] = DirectAllocation(cfg["strategy"], {
                    "broker": cfg["broker"],
                    "symbol": cfg["symbol"],
                    "quantity": cfg["quantity"],
                    "allocation_pct": cfg.get("allocation_pct", 100.0),
                    "enabled": cfg.get("enabled", True),
                })
                self.log(f"Prop allocation [{name}] -> {cfg['broker']}")

    def _load_active_trades(self):
        """Load active trades from disk so they survive restarts."""
        try:
            if os.path.exists(TRADES_FILE):
                with open(TRADES_FILE, "r") as f:
                    saved = json.load(f)
                for name, trade in saved.items():
                    if trade.get("status") in ("OPEN", "SIM"):
                        # Reconstruct the signal object
                        sig_data = trade.get("signal", {})
                        signal = Signal(
                            direction=sig_data.get("direction", "UP"),
                            confidence=sig_data.get("confidence", 0.5),
                            symbol=sig_data.get("symbol", "SPY"),
                            quantity=sig_data.get("quantity", 1),
                        )
                        trade["signal"] = signal
                        if "entry_time" in trade and isinstance(trade["entry_time"], str):
                            try:
                                trade["entry_time"] = datetime.fromisoformat(trade["entry_time"])
                            except Exception:
                                trade["entry_time"] = datetime.now(ET)
                        self.active_trades[name] = trade
                if self.active_trades:
                    print(f"Restored {len(self.active_trades)} active trade(s) from disk")
        except Exception as e:
            print(f"Could not load active trades: {e}")

    def _save_active_trades(self):
        """Save active trades to disk."""
        try:
            to_save = {}
            for name, trade in self.active_trades.items():
                t = dict(trade)
                # Convert signal to dict for JSON
                if hasattr(t.get("signal"), "direction"):
                    sig = t["signal"]
                    t["signal"] = {
                        "direction": sig.direction,
                        "confidence": sig.confidence,
                        "symbol": sig.symbol,
                        "quantity": sig.quantity,
                    }
                # Convert datetime to string
                if hasattr(t.get("entry_time"), "isoformat"):
                    t["entry_time"] = t["entry_time"].isoformat()
                to_save[name] = t
            with open(TRADES_FILE, "w") as f:
                json.dump(to_save, f, indent=2)
        except Exception as e:
            print(f"Could not save active trades: {e}")

    def _load_portfolio_config(self):
        self.portfolios, self.allocations = load_portfolios()

    def save_portfolio_config(self):
        save_portfolios(self.portfolios, self.allocations)

    def log(self, msg: str):
        ts = datetime.now(ET).strftime("%H:%M:%S")
        line = f"{ts} {msg}"
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-100:]
        print(line)

    # ── Circuit breaker ──
    def activate_circuit_breaker(self):
        self.log("CIRCUIT BREAKER ACTIVATED — closing all positions")
        self._circuit_breaker_active = True
        self._circuit_breaker_time = datetime.now(ET)
        for name in list(self.active_trades):
            trade = self.active_trades[name]
            if trade["status"] in ("OPEN", "SIM"):
                self.log(f"Emergency close: [{name}]")
                self.close_order(name)
        self.log("All orders blocked until re-authorization")

    def deactivate_circuit_breaker(self):
        self._circuit_breaker_active = False
        self._circuit_breaker_time = None
        self.log("Circuit breaker deactivated — trading resumed")

    @property
    def circuit_breaker_active(self) -> bool:
        return self._circuit_breaker_active

    # ── Brokers ──
    def _create_broker(self, broker_id: str, cfg: dict) -> BaseBroker:
        if cfg["type"] == "tradier":
            return TradierBroker(cfg.get("name", broker_id), cfg)
        elif cfg["type"] == "webhook":
            return TradersPostBroker(cfg.get("name", broker_id), cfg)
        else:
            raise ValueError(f"Unknown broker type: {cfg['type']}")

    def init_brokers(self):
        for broker_id, cfg in BROKERS.items():
            try:
                broker = self._create_broker(broker_id, cfg)
                connected = broker.connect()
                self.brokers[broker_id] = broker
                status = "connected" if connected else f"{broker.last_error}"
                self.log(f"Broker [{broker_id}] {cfg.get('name', '')}: {status}")
            except Exception as e:
                self.log(f"Broker [{broker_id}] error: {e}")

    # ── Strategies ──
    def register_strategy(self, strategy: BaseStrategy):
        self.strategies[strategy.name] = strategy
        route = ROUTES.get(strategy.name, {})
        self.routes[strategy.name] = route
        strategy.enabled = route.get("enabled", False)
        in_portfolio = any(strategy.name in p.strategy_names for p in self.portfolios.values())
        in_allocation = strategy.name in self.allocations
        if in_portfolio or in_allocation:
            strategy.enabled = True
        location = "portfolio" if in_portfolio else ("direct" if in_allocation else f"broker={route.get('broker', 'none')}")
        self.log(f"Strategy [{strategy.name}]: {'enabled' if strategy.enabled else 'disabled'} -> {location}")

    def init_strategies(self):
        for name, strategy in self.strategies.items():
            if not strategy.enabled:
                continue
            try:
                self.log(f"Initializing [{name}]...")
                ok = strategy.initialize()
                self.log(f"[{name}] {'ready' if ok else 'init failed'}")
            except Exception as e:
                self.log(f"[{name}] init error: {e}")

    # ── Routing ──
    def _resolve_route(self, strategy_name: str) -> dict:
        """Resolve single route (used for closes)."""
        for pname, portfolio in self.portfolios.items():
            if strategy_name in portfolio.strategy_names and portfolio.enabled:
                return {"type": "portfolio", "portfolio": pname, "broker": portfolio.broker_id}
        if strategy_name in self.allocations:
            alloc = self.allocations[strategy_name]
            if alloc.enabled:
                return {"type": "direct", "broker": alloc.broker_id, "symbol": alloc.symbol, "quantity": alloc.get_effective_quantity()}
        route = self.routes.get(strategy_name, {})
        return {"type": "legacy", "broker": route.get("broker", ""), "symbol": route.get("symbol", "SPY"), "quantity": route.get("quantity", 1)}

    def _resolve_all_routes(self, strategy_name: str) -> list:
        """Resolve ALL enabled destinations for a strategy (multi-broker support)."""
        routes = []
        # Check portfolios
        for pname, portfolio in self.portfolios.items():
            if strategy_name in portfolio.strategy_names and portfolio.enabled:
                routes.append({"type": "portfolio", "portfolio": pname, "broker": portfolio.broker_id, "route_id": f"port_{pname}"})
        # Check allocations
        if strategy_name in self.allocations:
            alloc = self.allocations[strategy_name]
            if alloc.enabled:
                routes.append({"type": "direct", "broker": alloc.broker_id, "symbol": alloc.symbol, "quantity": alloc.get_effective_quantity(), "route_id": f"alloc_{strategy_name}"})
        # Check legacy routes
        route = self.routes.get(strategy_name, {})
        if route.get("enabled", True) and route.get("broker"):
            routes.append({"type": "legacy", "broker": route.get("broker", ""), "symbol": route.get("symbol", "SPY"), "quantity": route.get("quantity", 1), "route_id": strategy_name})
        return routes

    def _get_broker(self, broker_id: str) -> Optional[BaseBroker]:
        return self.brokers.get(broker_id)

    # ── Orders ──
    def place_order(self, strategy_name: str, signal: Signal) -> bool:
        if self._circuit_breaker_active:
            self.log(f"[{strategy_name}] blocked — circuit breaker active")
            return False
        routing = self._resolve_route(strategy_name)
        broker = self._get_broker(routing["broker"])

        # Get account equity from broker (if available)
        equity = 0
        if broker:
            try:
                info = broker.get_account_info()
                equity = info.equity or 0
            except Exception:
                pass

        if routing["type"] == "portfolio":
            portfolio = self.portfolios[routing["portfolio"]]
            symbol = signal.symbol
            if equity > 0:
                asset_data = get_asset_data([symbol])
                sizes = portfolio.calculate_position_sizes(equity, asset_data)
                quantity = sizes.get(symbol, 1)
            else:
                quantity = 1
            if not portfolio.risk_ok(equity):
                self.log(f"[{strategy_name}] blocked — portfolio [{portfolio.name}] daily loss limit reached")
                return False
            self.log(f"[{strategy_name}] via portfolio [{portfolio.name}] -> {quantity}x {symbol} (equity=${equity:,.0f})")

        elif routing["type"] == "direct":
            # Check if this allocation has dynamic sizing enabled
            alloc_name = strategy_name
            alloc = self.allocations.get(alloc_name)
            symbol = routing["symbol"]

            if alloc and equity > 0 and alloc.allocation_pct < 100:
                # Dynamic sizing: use allocation percentage of equity
                asset_data = get_asset_data([symbol])
                price_data = asset_data.get(symbol, {})
                price = price_data.get("price", 100)
                point_value = price_data.get("point_value", 100)
                # Calculate dollar amount for this allocation
                alloc_dollars = equity * (alloc.allocation_pct / 100.0)
                # Calculate contracts based on price
                cost_per_contract = price * point_value / 100  # rough cost per option/contract
                if cost_per_contract > 0:
                    quantity = max(1, int(alloc_dollars / cost_per_contract))
                else:
                    quantity = alloc.quantity
                self.log(f"[{strategy_name}] dynamic size: ${alloc_dollars:,.0f} alloc -> {quantity}x {symbol}")
            else:
                quantity = routing["quantity"]
            self.log(f"[{strategy_name}] direct -> {quantity}x {symbol}")

        else:
            symbol = routing.get("symbol", signal.symbol)
            quantity = routing.get("quantity", 1)

            # If broker provides equity, do basic sizing
            if equity > 0:
                asset_data = get_asset_data([symbol])
                price_data = asset_data.get(symbol, {})
                price = price_data.get("price", 100)
                point_value = price_data.get("point_value", 100)
                # For legacy routes, use risk_pct from daily loss limit config
                risk_budget = equity * 0.01  # 1% default risk
                expected_move = price * (price_data.get("avg_move_pct", 0.20) / 100.0) * point_value
                if expected_move > 0:
                    calc_qty = max(1, int(risk_budget / expected_move))
                    if calc_qty != quantity:
                        self.log(f"[{strategy_name}] dynamic size: {calc_qty}x {symbol} (from equity ${equity:,.0f})")
                        quantity = calc_qty
        else:
            symbol = routing.get("symbol", signal.symbol)
            quantity = routing.get("quantity", signal.quantity)

        if SIM_MODE:
            self.log(f"[SIM] {strategy_name} -> {signal.direction} {quantity}x {symbol} (conf={signal.confidence:.1%})")
            self.active_trades[strategy_name] = {"signal": signal, "entry_time": datetime.now(ET), "status": "SIM", "quantity": quantity, "symbol": symbol}
            self._save_active_trades()
            return True
        if not broker:
            self.log(f"[{strategy_name}] no broker assigned")
            return False
        if not broker.is_connected:
            self.log(f"[{strategy_name}] broker not connected")
            return False
        self.log(f"[ORDER] {strategy_name} -> {broker.name}: {signal.direction} {quantity}x {symbol}")
        result = broker.place_order(direction=signal.direction, symbol=symbol, quantity=quantity)
        if result.success:
            self.log(f"[{strategy_name}] filled: {result.message}")
            self.active_trades[strategy_name] = {"signal": signal, "entry_time": datetime.now(ET), "order_id": result.order_id, "occ_symbol": result.symbol, "status": "OPEN", "quantity": quantity, "symbol": symbol}
            self._save_active_trades()
        else:
            self.log(f"[{strategy_name}] failed: {result.message}")
        return result.success

    def close_order(self, strategy_name: str) -> bool:
        trade = self.active_trades.get(strategy_name)
        if not trade:
            return False
        routing = self._resolve_route(strategy_name)
        broker = self._get_broker(routing["broker"])
        symbol = trade.get("symbol", routing.get("symbol", "SPY"))
        quantity = trade.get("quantity", routing.get("quantity", 1))
        if SIM_MODE:
            self.log(f"[SIM] {strategy_name} closed")
            trade["status"] = "CLOSED"
            self._save_active_trades()
            return True
        if not broker:
            self.log(f"[{strategy_name}] no broker for close")
            return False
        result = broker.close_position(symbol=symbol, quantity=quantity, direction=trade["signal"].direction, occ_symbol=trade.get("occ_symbol"))
        if result.success:
            self.log(f"[{strategy_name}] closed: {result.message}")
            trade["status"] = "CLOSED"
            self._save_active_trades()
        else:
            self.log(f"[{strategy_name}] close failed: {result.message}")
        return result.success

    # ── Risk ──
    def risk_ok(self) -> bool:
        loss = -min(0.0, self.day_pnl)
        remaining = DAILY_LOSS_LIMIT - loss
        if remaining < DAILY_LOSS_BUFFER:
            self.log(f"Daily loss guard: ${remaining:.0f} remaining")
            return False
        return True

    # ── Main loop ──
    def run(self):
        self._running = True
        mode = "SIM" if SIM_MODE else "LIVE"
        self.log("=" * 58)
        self.log(f"Trading Command Center — mode={mode}")
        self.log(f"Brokers: {len(self.brokers)} | Strategies: {len(self.strategies)}")
        self.log("=" * 58)
        self.init_brokers()
        self.init_strategies()
        last_reset = None
        while self._running:
            now = datetime.now(ET)
            today = now.date()
            if self._circuit_breaker_active:
                time.sleep(10)
                continue
            if now.hour == 0 and now.minute < 5 and last_reset != today:
                self.log("Midnight — resetting all strategies")
                self.day_pnl = 0.0
                self.active_trades.clear()
                for strategy in self.strategies.values():
                    strategy.reset_daily()
                for portfolio in self.portfolios.values():
                    portfolio.day_pnl = 0.0
                self.init_strategies()
                last_reset = today
                time.sleep(60)
                continue
            if now.weekday() >= 5:
                time.sleep(300)
                continue
            if now.hour < 9:
                time.sleep(30)
                continue
            if now.hour >= 12:
                for name in list(self.active_trades):
                    if self.active_trades[name]["status"] == "OPEN":
                        self.log(f"Noon hard stop — closing [{name}]")
                        self.close_order(name)
                time.sleep(60)
                continue
            for name, strategy in self.strategies.items():
                if not strategy.is_ready:
                    continue
                win_start, win_end = strategy.get_trading_window()
                current_time = now.time()
                if not (win_start <= current_time <= win_end):
                    if name in self.active_trades:
                        trade = self.active_trades[name]
                        if trade["status"] in ("OPEN", "SIM"):
                            if strategy.should_exit(now, 0, 0, trade["signal"].direction):
                                self.log(f"Exit signal — [{name}]")
                                self.close_order(name)
                                strategy.record_trade(trade["signal"], "CLOSED")
                    continue
                if name in self.active_trades:
                    trade = self.active_trades[name]
                    if trade["status"] in ("OPEN", "SIM"):
                        if strategy.should_exit(now, 0, 0, trade["signal"].direction):
                            self.log(f"Exit signal — [{name}]")
                            self.close_order(name)
                            strategy.record_trade(trade["signal"], "CLOSED")
                    continue
                if strategy._today_traded:
                    continue
                if not self.risk_ok():
                    continue
                try:
                    signal = strategy.check_signal(now)
                    if signal:
                        self.log(f"[{name}] signal: {signal.direction} ({signal.confidence:.1%})")
                        all_routes = self._resolve_all_routes(name)
                        if all_routes:
                            for route in all_routes:
                                route_id = route.get("route_id", name)
                                trade_key = route_id if len(all_routes) > 1 else name
                                if trade_key not in self.active_trades:
                                    self.log(f"[{name}] -> {route.get('broker', '?')} ({route_id})")
                                    self.place_order(trade_key, signal)
                        else:
                            self.place_order(name, signal)
                except Exception as e:
                    self.log(f"[{name}] signal error: {e}")
            time.sleep(10)

    # ── Dashboard state ──
    def get_state(self) -> dict:
        broker_states = {}
        for bid, broker in self.brokers.items():
            try:
                info = broker.get_account_info()
                broker_states[bid] = {"name": broker.name, "type": broker.broker_type, "connected": broker.is_connected, "equity": info.equity, "cash": info.cash, "day_pnl": info.day_pnl, "positions": [p.__dict__ for p in info.positions], "error": info.error}
            except Exception as e:
                broker_states[bid] = {"name": broker.name, "connected": False, "error": str(e)}
        strategy_states = {}
        for name, strategy in self.strategies.items():
            s = strategy.to_dict()
            route = self.routes.get(name, {})
            s["broker"] = route.get("broker", "none")
            s["quantity"] = route.get("quantity", 1)
            s["symbol"] = route.get("symbol", "SPY")
            trade = self.active_trades.get(name)
            if trade:
                s["active_trade"] = {"direction": trade["signal"].direction, "confidence": trade["signal"].confidence, "entry_time": trade["entry_time"].strftime("%H:%M:%S"), "status": trade["status"]}
            strategy_states[name] = s
        return {
            "sim_mode": SIM_MODE,
            "circuit_breaker": self._circuit_breaker_active,
            "circuit_breaker_time": self._circuit_breaker_time.strftime("%H:%M:%S") if self._circuit_breaker_time else None,
            "brokers": broker_states, "strategies": strategy_states,
            "portfolios": {n: p.to_dict() for n, p in self.portfolios.items()},
            "allocations": {n: a.to_dict() for n, a in self.allocations.items()},
            "active_trades": {k: {"direction": v["signal"].direction, "status": v["status"], "symbol": v.get("symbol", "SPY")} for k, v in self.active_trades.items()},
            "log": self.log_lines, "day_pnl": self.day_pnl,
        }
