# router.py — Strategy orchestrator + order router
# Runs each strategy on its schedule, routes orders to the assigned broker

import time
import threading
import pytz
from datetime import datetime, date
from typing import Dict, List, Optional

from brokers import TradierBroker, TradersPostBroker
from brokers.base import BaseBroker
from strategies.base import BaseStrategy, Signal
from config import BROKERS, ROUTES, SIM_MODE, DAILY_LOSS_LIMIT, DAILY_LOSS_BUFFER

ET = pytz.timezone("America/New_York")


class Router:
    """
    The command center. Manages brokers, strategies, and routing.
    Dashboard reads from this object.
    """

    def __init__(self):
        self.brokers: Dict[str, BaseBroker] = {}
        self.strategies: Dict[str, BaseStrategy] = {}
        self.routes: Dict[str, dict] = {}     # strategy_name -> route config
        self.active_trades: Dict[str, dict] = {}  # strategy_name -> trade info
        self.log_lines: List[str] = []
        self.day_pnl: float = 0.0
        self._running = False

    def log(self, msg: str):
        ts = datetime.now(ET).strftime("%H:%M:%S")
        line = f"{ts} {msg}"
        self.log_lines.append(line)
        self.log_lines = self.log_lines[-100:]
        print(line)

    # ══════════════════════════════════════════════════════════
    #  BROKER MANAGEMENT
    # ══════════════════════════════════════════════════════════

    def _create_broker(self, broker_id: str, cfg: dict) -> BaseBroker:
        """Factory: create the right broker type from config."""
        if cfg["type"] == "tradier":
            return TradierBroker(cfg.get("name", broker_id), cfg)
        elif cfg["type"] == "webhook":
            return TradersPostBroker(cfg.get("name", broker_id), cfg)
        else:
            raise ValueError(f"Unknown broker type: {cfg['type']}")

    def init_brokers(self):
        """Initialize all configured brokers."""
        for broker_id, cfg in BROKERS.items():
            try:
                broker = self._create_broker(broker_id, cfg)
                connected = broker.connect()
                self.brokers[broker_id] = broker
                status = "✅ connected" if connected else f"❌ {broker.last_error}"
                self.log(f"Broker [{broker_id}] {cfg.get('name', '')}: {status}")
            except Exception as e:
                self.log(f"Broker [{broker_id}] error: {e}")

    # ══════════════════════════════════════════════════════════
    #  STRATEGY MANAGEMENT
    # ══════════════════════════════════════════════════════════

    def register_strategy(self, strategy: BaseStrategy):
        """Register a strategy and set up its routing."""
        self.strategies[strategy.name] = strategy
        route = ROUTES.get(strategy.name, {})
        self.routes[strategy.name] = route
        strategy.enabled = route.get("enabled", False)
        self.log(f"Strategy [{strategy.name}]: "
                 f"{'enabled' if strategy.enabled else 'disabled'} "
                 f"→ broker={route.get('broker', 'none')}")

    def init_strategies(self):
        """Initialize (train) all registered strategies."""
        for name, strategy in self.strategies.items():
            if not strategy.enabled:
                continue
            try:
                self.log(f"Initializing [{name}]...")
                ok = strategy.initialize()
                if ok:
                    self.log(f"✅ [{name}] ready")
                else:
                    self.log(f"⚠️ [{name}] initialization failed")
            except Exception as e:
                self.log(f"❌ [{name}] init error: {e}")

    # ══════════════════════════════════════════════════════════
    #  ORDER ROUTING
    # ══════════════════════════════════════════════════════════

    def _get_broker_for_strategy(self, strategy_name: str) -> Optional[BaseBroker]:
        """Look up which broker a strategy routes to."""
        route = self.routes.get(strategy_name, {})
        broker_id = route.get("broker", "")
        return self.brokers.get(broker_id)

    def place_order(self, strategy_name: str, signal: Signal) -> bool:
        """Route an order from a strategy to its assigned broker."""
        route = self.routes.get(strategy_name, {})
        broker = self._get_broker_for_strategy(strategy_name)

        symbol = route.get("symbol", signal.symbol)
        quantity = route.get("quantity", signal.quantity)

        if SIM_MODE:
            self.log(f"[SIM] {strategy_name} → {signal.direction} "
                     f"{quantity}x {symbol} "
                     f"(conf={signal.confidence:.1%})")
            self.active_trades[strategy_name] = {
                "signal": signal,
                "entry_time": datetime.now(ET),
                "status": "SIM",
            }
            return True

        if not broker:
            self.log(f"⚠️ [{strategy_name}] no broker assigned "
                     f"(route={route.get('broker', 'none')})")
            return False

        if not broker.is_connected:
            self.log(f"⚠️ [{strategy_name}] broker not connected")
            return False

        self.log(f"[ORDER] {strategy_name} → {broker.name}: "
                 f"{signal.direction} {quantity}x {symbol}")

        result = broker.place_order(
            direction=signal.direction,
            symbol=symbol,
            quantity=quantity,
        )

        if result.success:
            self.log(f"✅ [{strategy_name}] filled: {result.message}")
            self.active_trades[strategy_name] = {
                "signal": signal,
                "entry_time": datetime.now(ET),
                "order_id": result.order_id,
                "occ_symbol": result.symbol,
                "status": "OPEN",
            }
        else:
            self.log(f"❌ [{strategy_name}] failed: {result.message}")

        return result.success

    def close_order(self, strategy_name: str) -> bool:
        """Close an active trade for a strategy."""
        trade = self.active_trades.get(strategy_name)
        if not trade:
            return False

        route = self.routes.get(strategy_name, {})
        broker = self._get_broker_for_strategy(strategy_name)
        symbol = route.get("symbol", "SPY")
        quantity = route.get("quantity", 1)

        if SIM_MODE:
            self.log(f"[SIM] {strategy_name} closed")
            trade["status"] = "CLOSED"
            return True

        if not broker:
            self.log(f"⚠️ [{strategy_name}] no broker for close")
            return False

        result = broker.close_position(
            symbol=symbol,
            quantity=quantity,
            direction=trade["signal"].direction,
            occ_symbol=trade.get("occ_symbol"),
        )

        if result.success:
            self.log(f"✅ [{strategy_name}] closed: {result.message}")
            trade["status"] = "CLOSED"
        else:
            self.log(f"❌ [{strategy_name}] close failed: {result.message}")

        return result.success

    # ══════════════════════════════════════════════════════════
    #  RISK
    # ══════════════════════════════════════════════════════════

    def risk_ok(self) -> bool:
        loss = -min(0.0, self.day_pnl)
        remaining = DAILY_LOSS_LIMIT - loss
        if remaining < DAILY_LOSS_BUFFER:
            self.log(f"⚠️ Daily loss guard: ${remaining:.0f} remaining")
            return False
        return True

    # ══════════════════════════════════════════════════════════
    #  MAIN LOOP
    # ══════════════════════════════════════════════════════════

    def run(self):
        """Main trading loop — runs forever."""
        self._running = True
        mode = "SIM" if SIM_MODE else "LIVE"
        self.log("═" * 58)
        self.log(f"Trading Command Center — mode={mode}")
        self.log(f"Brokers: {len(self.brokers)} | "
                 f"Strategies: {len(self.strategies)}")
        self.log("═" * 58)

        self.init_brokers()
        self.init_strategies()

        last_reset = None

        while self._running:
            now = datetime.now(ET)
            today = now.date()

            # ── Midnight reset ────────────────────────────────
            if now.hour == 0 and now.minute < 5 and last_reset != today:
                self.log("Midnight — resetting all strategies")
                self.day_pnl = 0.0
                self.active_trades.clear()
                for strategy in self.strategies.values():
                    strategy.reset_daily()
                # Retrain models
                self.init_strategies()
                last_reset = today
                time.sleep(60)
                continue

            # ── Weekend ───────────────────────────────────────
            if now.weekday() >= 5:
                time.sleep(300)
                continue

            # ── Too early ─────────────────────────────────────
            if now.hour < 9:
                time.sleep(30)
                continue

            # ── Noon hard stop ────────────────────────────────
            if now.hour >= 12:
                for name in list(self.active_trades):
                    if self.active_trades[name]["status"] == "OPEN":
                        self.log(f"Noon hard stop — closing [{name}]")
                        self.close_order(name)
                time.sleep(60)
                continue

            # ── Check each strategy ───────────────────────────
            for name, strategy in self.strategies.items():
                if not strategy.is_ready:
                    continue

                # Check if in trading window
                win_start, win_end = strategy.get_trading_window()
                current_time = now.time()
                if not (win_start <= current_time <= win_end):
                    # But check active trades for exit
                    if name in self.active_trades:
                        trade = self.active_trades[name]
                        if trade["status"] in ("OPEN", "SIM"):
                            signal = trade["signal"]
                            if strategy.should_exit(now, 0, 0,
                                                    signal.direction):
                                self.log(f"Exit signal — [{name}]")
                                self.close_order(name)
                                strategy.record_trade(signal, "CLOSED")
                    continue

                # Already in a trade for this strategy?
                if name in self.active_trades:
                    trade = self.active_trades[name]
                    if trade["status"] in ("OPEN", "SIM"):
                        signal = trade["signal"]
                        if strategy.should_exit(now, 0, 0,
                                                signal.direction):
                            self.log(f"Exit signal — [{name}]")
                            self.close_order(name)
                            strategy.record_trade(signal, "CLOSED")
                    continue

                # Already traded today?
                if strategy._today_traded:
                    continue

                # Risk check
                if not self.risk_ok():
                    continue

                # Check for signal
                try:
                    signal = strategy.check_signal(now)
                    if signal:
                        self.log(f"🔔 [{name}] → {signal.direction} "
                                 f"({signal.confidence:.1%})")
                        self.place_order(name, signal)
                except Exception as e:
                    self.log(f"❌ [{name}] signal error: {e}")

            time.sleep(10)

    # ══════════════════════════════════════════════════════════
    #  DASHBOARD STATE
    # ══════════════════════════════════════════════════════════

    def get_state(self) -> dict:
        """Full state snapshot for the dashboard."""
        broker_states = {}
        for bid, broker in self.brokers.items():
            try:
                info = broker.get_account_info()
                broker_states[bid] = {
                    "name": broker.name,
                    "type": broker.broker_type,
                    "connected": broker.is_connected,
                    "equity": info.equity,
                    "cash": info.cash,
                    "day_pnl": info.day_pnl,
                    "positions": [p.__dict__ for p in info.positions],
                    "error": info.error,
                }
            except Exception as e:
                broker_states[bid] = {
                    "name": broker.name,
                    "connected": False,
                    "error": str(e),
                }

        strategy_states = {}
        for name, strategy in self.strategies.items():
            s = strategy.to_dict()
            route = self.routes.get(name, {})
            s["broker"] = route.get("broker", "none")
            s["quantity"] = route.get("quantity", 1)
            s["symbol"] = route.get("symbol", "SPY")
            # Active trade info
            trade = self.active_trades.get(name)
            if trade:
                s["active_trade"] = {
                    "direction": trade["signal"].direction,
                    "confidence": trade["signal"].confidence,
                    "entry_time": trade["entry_time"].strftime("%H:%M:%S"),
                    "status": trade["status"],
                }
            strategy_states[name] = s

        return {
            "sim_mode": SIM_MODE,
            "brokers": broker_states,
            "strategies": strategy_states,
            "active_trades": {
                k: {
                    "direction": v["signal"].direction,
                    "status": v["status"],
                }
                for k, v in self.active_trades.items()
            },
            "log": self.log_lines,
            "day_pnl": self.day_pnl,
        }
