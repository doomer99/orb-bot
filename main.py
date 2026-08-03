# main.py — Entry point for the Trading Command Center
import threading
from router import Router
from config import discover_strategies

router = Router()
for StrategyClass in discover_strategies():
    router.register_strategy(StrategyClass())

threading.Thread(target=router.run, daemon=True).start()
