"""
Smart Money Score Engine.

Combines 6 free data sources into a single directional score
(-100 to +100) for scalp trade confirmation.

Weighting (tuned for intraday scalp edge):
  - Options flow:      30%  (most predictive for intraday)
  - Market internals:  25%  (real-time breadth)
  - Pre-market levels: 20%  (gap + level context)
  - Put/Call ratio:    10%  (sentiment)
  - Insider filings:   10%  (medium-term bias)
  - 13F holdings:       5%  (long-term context)
"""

from __future__ import annotations

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SmartMoneyScore:
    score: float                # -100 (strong sell) to +100 (strong buy)
    bias: str                  # "STRONG_BULL" | "BULL" | "NEUTRAL" | "BEAR" | "STRONG_BEAR"
    options_bias: str
    internals_bias: str
    premarket_bias: str
    insider_bias: str
    institutional_bias: str
    pcr: float                 # put/call ratio
    confidence: float          # 0-1 (how many sources agree)
    components: dict = field(default_factory=dict)
    timestamp: float = 0.0


_cache: Optional[SmartMoneyScore] = None
_cache_ts: float = 0.0
_cache_lock = threading.Lock()
CACHE_TTL = 120  # 2 minutes


# Weights must sum to 1.0
WEIGHTS = {
    "options":       0.30,
    "internals":     0.25,
    "premarket":     0.20,
    "pcr":           0.10,
    "insider":       0.10,
    "institutional": 0.05,
}


def compute_smart_money_score(force_refresh: bool = False) -> SmartMoneyScore:
    """Compute composite Smart Money Score from all 6 data sources."""
    global _cache, _cache_ts
    if not force_refresh:
        with _cache_lock:
            if _cache and (time.time() - _cache_ts) < CACHE_TTL:
                return _cache

    components: dict[str, float] = {}
    biases: dict[str, str] = {}

    # 1. Options flow (30%)
    opt_score, opt_bias = _score_options()
    components["options"] = opt_score
    biases["options"] = opt_bias

    # 2. Market internals (25%)
    int_score, int_bias = _score_internals()
    components["internals"] = int_score
    biases["internals"] = int_bias

    # 3. Pre-market levels (20%)
    pre_score, pre_bias = _score_premarket()
    components["premarket"] = pre_score
    biases["premarket"] = pre_bias

    # 4. Put/Call ratio (10%)
    pcr_score, pcr_bias, pcr_val = _score_pcr()
    components["pcr"] = pcr_score
    biases["pcr"] = pcr_bias

    # 5. Insider filings (10%)
    ins_score, ins_bias = _score_insider()
    components["insider"] = ins_score
    biases["insider"] = ins_bias

    # 6. 13F institutional (5%)
    inst_score, inst_bias = _score_institutional()
    components["institutional"] = inst_score
    biases["institutional"] = inst_bias

    # Weighted composite
    total_score = sum(components[k] * WEIGHTS[k] for k in WEIGHTS)
    total_score = max(-100, min(100, total_score))

    # Confidence: fraction of sources that agree on direction
    directions = []
    for k, s in components.items():
        if s > 10:
            directions.append(1)
        elif s < -10:
            directions.append(-1)
        else:
            directions.append(0)
    if directions:
        bullish = sum(1 for d in directions if d > 0)
        bearish = sum(1 for d in directions if d < 0)
        majority = max(bullish, bearish)
        confidence = majority / len(directions)
    else:
        confidence = 0.0

    # Overall bias label
    if total_score >= 50:
        bias = "STRONG_BULL"
    elif total_score >= 20:
        bias = "BULL"
    elif total_score <= -50:
        bias = "STRONG_BEAR"
    elif total_score <= -20:
        bias = "BEAR"
    else:
        bias = "NEUTRAL"

    logger.info(
        "Smart Money Score: %.1f (%s) | conf=%.0f%% | opt=%s int=%s pre=%s ins=%s inst=%s pcr=%.2f",
        total_score, bias, confidence * 100,
        biases["options"], biases["internals"], biases["premarket"],
        biases["insider"], biases["institutional"], pcr_val,
    )

    result = SmartMoneyScore(
        score=round(total_score, 1),
        bias=bias,
        options_bias=biases["options"],
        internals_bias=biases["internals"],
        premarket_bias=biases["premarket"],
        insider_bias=biases["insider"],
        institutional_bias=biases["institutional"],
        pcr=pcr_val,
        confidence=round(confidence, 2),
        components={k: round(v, 1) for k, v in components.items()},
        timestamp=time.time(),
    )

    with _cache_lock:
        _cache = result
        _cache_ts = time.time()

    return result


# ---------------------------------------------------------------------------
# Individual source scorers: each returns (score -100..+100, bias_label)
# ---------------------------------------------------------------------------

def _score_options() -> tuple[float, str]:
    try:
        from data.options_flow import scan_options_flow
        sig = scan_options_flow()

        # Score based on unusual activity balance and net premium
        score = 0.0
        unusual_diff = sig.unusual_calls - sig.unusual_puts
        score += max(-50, min(50, unusual_diff * 12))

        # Net premium direction
        if sig.net_premium > 0:
            score += 25
        elif sig.net_premium < 0:
            score -= 25

        score = max(-100, min(100, score))
        return score, sig.bias
    except Exception as e:
        logger.debug("Options score failed: %s", e)
        return 0.0, "NEUTRAL"


def _score_internals() -> tuple[float, str]:
    try:
        from data.market_internals import fetch_market_internals
        sig = fetch_market_internals()

        # ADL contribution
        score = max(-60, min(60, sig.adl * 3))

        # TRIN contribution (inverted: low TRIN = bullish)
        if sig.trin < 0.8:
            score += 20
        elif sig.trin > 1.2:
            score -= 20

        # Breadth extreme bonus
        if sig.breadth_pct > 70:
            score += 20
        elif sig.breadth_pct < 30:
            score -= 20

        score = max(-100, min(100, score))
        return score, sig.bias
    except Exception as e:
        logger.debug("Internals score failed: %s", e)
        return 0.0, "NEUTRAL"


def _score_premarket() -> tuple[float, str]:
    try:
        from data.premarket_levels import fetch_premarket_levels
        sig = fetch_premarket_levels()

        score = 0.0
        # Gap direction
        if sig.gap_direction == "GAP_UP":
            score += min(40, sig.gap_pct * 20)
        elif sig.gap_direction == "GAP_DOWN":
            score -= min(40, abs(sig.gap_pct) * 20)

        # Price vs prior levels
        if sig.current_price > sig.prior_high:
            score += 30
        elif sig.current_price < sig.prior_low:
            score -= 30
        elif sig.current_price > sig.prior_close:
            score += 15
        elif sig.current_price < sig.prior_close:
            score -= 15

        score = max(-100, min(100, score))
        return score, sig.bias
    except Exception as e:
        logger.debug("Premarket score failed: %s", e)
        return 0.0, "NEUTRAL"


def _score_pcr() -> tuple[float, str, float]:
    """Score from put/call ratio (also returns raw PCR)."""
    try:
        from data.options_flow import scan_options_flow
        sig = scan_options_flow()
        pcr = sig.put_call_ratio

        # Standard interpretation: low PCR = bullish, high PCR = bearish
        # With contrarian twist at extremes
        if pcr < 0.5:
            score = 50  # very bullish
        elif pcr < 0.7:
            score = 30
        elif pcr < 0.9:
            score = 10
        elif pcr < 1.1:
            score = 0
        elif pcr < 1.3:
            score = -30
        else:
            score = -50  # very bearish (contrarian: could be capitulation)

        bias = "BULLISH" if score > 10 else ("BEARISH" if score < -10 else "NEUTRAL")
        return score, bias, pcr
    except Exception as e:
        logger.debug("PCR score failed: %s", e)
        return 0.0, "NEUTRAL", 1.0


def _score_insider() -> tuple[float, str]:
    try:
        from data.insider_tracker import fetch_insider_signal
        sig = fetch_insider_signal()

        score = 0.0
        # Cluster buying is very bullish
        score += len(sig.cluster_buys) * 25
        score -= len(sig.cluster_sells) * 25

        # Net bias from filing counts
        if sig.total_buys > sig.total_sells:
            score += 15
        elif sig.total_sells > sig.total_buys:
            score -= 15

        score = max(-100, min(100, score))
        return score, sig.net_bias
    except Exception as e:
        logger.debug("Insider score failed: %s", e)
        return 0.0, "NEUTRAL"


def _score_institutional() -> tuple[float, str]:
    try:
        from data.institutional_tracker import fetch_institutional_signal
        sig = fetch_institutional_signal()

        score = 0.0
        if sig.net_bias == "BULLISH":
            score = 40
        elif sig.net_bias == "BEARISH":
            score = -40

        # Bonus for breadth of funds buying
        score += len(sig.top_buys) * 5
        score -= len(sig.top_sells) * 5

        score = max(-100, min(100, score))
        return score, sig.net_bias
    except Exception as e:
        logger.debug("Institutional score failed: %s", e)
        return 0.0, "NEUTRAL"
