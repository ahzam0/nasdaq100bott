"""
Live broker: Alpaca Markets (primary), Interactive Brokers (backup).
Paper + live, WebSocket quotes/orders, failover.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# Optional: alpaca-trade-api, ib_insync
_alpaca = None
try:
    import alpaca_trade_api as ata
    _alpaca = ata
except ImportError:
    pass


def get_alpaca_client(paper: bool = True):
    """Return Alpaca REST client (paper or live) from env ALPACA_KEY, ALPACA_SECRET."""
    if _alpaca is None:
        return None
    key = os.environ.get("ALPACA_KEY", "").strip()
    secret = os.environ.get("ALPACA_SECRET", "").strip()
    if not key or not secret:
        return None
    base = "https://paper-api.alpaca.markets" if paper else "https://api.alpaca.markets"
    return _alpaca.REST(key, secret, base_url=base)


def submit_order_alpaca(
    symbol: str,
    qty: float,
    side: str,
    order_type: str = "limit",
    time_in_force: str = "day",
    limit_price: Optional[float] = None,
    client: Any = None,
) -> Optional[dict]:
    """Submit order via Alpaca. side: 'buy'|'sell', order_type: 'market'|'limit'."""
    if client is None:
        client = get_alpaca_client(paper=True)
    if client is None:
        logger.warning("Alpaca client not available")
        return None
    try:
        return client.submit_order(symbol=symbol, qty=qty, side=side, type=order_type, time_in_force=time_in_force, limit_price=limit_price)
    except Exception as e:
        logger.error("Alpaca order failed: %s", e)
        return None


def failover_to_ibkr() -> bool:
    """Switch to IBKR if Alpaca unavailable. Stub."""
    return False
