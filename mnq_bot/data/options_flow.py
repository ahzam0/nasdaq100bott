"""
Options unusual activity scanner + put/call ratio.

Scans QQQ and TQQQ options chains via yfinance (free, no API key)
to detect unusual institutional activity.

Unusual = strike where volume > 3x open_interest.
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

SYMBOLS = ["QQQ", "TQQQ"]
UNUSUAL_THRESHOLD = 3.0  # volume / open_interest
MAX_EXPIRATIONS = 3


@dataclass
class UnusualStrike:
    symbol: str
    expiry: str
    strike: float
    option_type: str       # "call" | "put"
    volume: int
    open_interest: int
    ratio: float           # volume / OI
    premium: float         # last_price * volume * 100


@dataclass
class OptionsFlowSignal:
    bias: str              # "BULLISH" | "BEARISH" | "NEUTRAL"
    unusual_calls: int
    unusual_puts: int
    net_premium: float     # call premium - put premium (positive = bullish)
    put_call_ratio: float  # total put vol / total call vol
    top_strikes: list[UnusualStrike] = field(default_factory=list)
    total_call_volume: int = 0
    total_put_volume: int = 0
    timestamp: float = 0.0


_cache: Optional[OptionsFlowSignal] = None
_cache_ts: float = 0.0
_cache_lock = threading.Lock()
CACHE_TTL = 300  # 5 minutes


def scan_options_flow() -> OptionsFlowSignal:
    """Scan QQQ/TQQQ options for unusual activity. Returns cached if fresh."""
    global _cache, _cache_ts
    with _cache_lock:
        if _cache and (time.time() - _cache_ts) < CACHE_TTL:
            return _cache

    try:
        signal = _fetch_options_flow()
    except Exception as e:
        logger.warning("Options flow scan failed: %s", e)
        signal = OptionsFlowSignal(
            bias="NEUTRAL", unusual_calls=0, unusual_puts=0,
            net_premium=0, put_call_ratio=1.0, timestamp=time.time(),
        )

    with _cache_lock:
        _cache = signal
        _cache_ts = time.time()
    return signal


def _fetch_options_flow() -> OptionsFlowSignal:
    import yfinance as yf

    all_unusual: list[UnusualStrike] = []
    total_call_vol = 0
    total_put_vol = 0
    total_call_premium = 0.0
    total_put_premium = 0.0

    for sym in SYMBOLS:
        try:
            ticker = yf.Ticker(sym)
            expirations = ticker.options
            if not expirations:
                continue

            for expiry in expirations[:MAX_EXPIRATIONS]:
                try:
                    chain = ticker.option_chain(expiry)
                except Exception:
                    continue

                # Calls
                for _, row in chain.calls.iterrows():
                    vol = int(row.get("volume", 0) or 0)
                    oi = int(row.get("openInterest", 0) or 0)
                    price = float(row.get("lastPrice", 0) or 0)
                    total_call_vol += vol
                    total_call_premium += price * vol * 100

                    if oi > 0 and vol > UNUSUAL_THRESHOLD * oi:
                        all_unusual.append(UnusualStrike(
                            symbol=sym, expiry=expiry,
                            strike=float(row["strike"]),
                            option_type="call", volume=vol,
                            open_interest=oi, ratio=vol / oi,
                            premium=price * vol * 100,
                        ))

                # Puts
                for _, row in chain.puts.iterrows():
                    vol = int(row.get("volume", 0) or 0)
                    oi = int(row.get("openInterest", 0) or 0)
                    price = float(row.get("lastPrice", 0) or 0)
                    total_put_vol += vol
                    total_put_premium += price * vol * 100

                    if oi > 0 and vol > UNUSUAL_THRESHOLD * oi:
                        all_unusual.append(UnusualStrike(
                            symbol=sym, expiry=expiry,
                            strike=float(row["strike"]),
                            option_type="put", volume=vol,
                            open_interest=oi, ratio=vol / oi,
                            premium=price * vol * 100,
                        ))
        except Exception as e:
            logger.debug("Options scan %s failed: %s", sym, e)

    unusual_calls = sum(1 for u in all_unusual if u.option_type == "call")
    unusual_puts = sum(1 for u in all_unusual if u.option_type == "put")
    net_premium = total_call_premium - total_put_premium
    pcr = total_put_vol / total_call_vol if total_call_vol > 0 else 1.0

    # Determine bias
    if unusual_calls > unusual_puts * 2 and net_premium > 0:
        bias = "BULLISH"
    elif unusual_puts > unusual_calls * 2 and net_premium < 0:
        bias = "BEARISH"
    elif net_premium > 0 and pcr < 0.7:
        bias = "BULLISH"
    elif net_premium < 0 and pcr > 1.0:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    # Sort by ratio descending, keep top 10
    all_unusual.sort(key=lambda x: x.ratio, reverse=True)

    logger.info("Options flow: %s | calls=%d puts=%d unusual_c=%d unusual_p=%d PCR=%.2f",
                bias, total_call_vol, total_put_vol, unusual_calls, unusual_puts, pcr)

    return OptionsFlowSignal(
        bias=bias,
        unusual_calls=unusual_calls,
        unusual_puts=unusual_puts,
        net_premium=net_premium,
        put_call_ratio=pcr,
        top_strikes=all_unusual[:10],
        total_call_volume=total_call_vol,
        total_put_volume=total_put_vol,
        timestamp=time.time(),
    )
