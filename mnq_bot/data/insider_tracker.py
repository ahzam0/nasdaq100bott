"""
SEC EDGAR Form 4 insider filing scanner.

Scrapes EDGAR for insider buys/sells of NASDAQ mega-cap stocks.
100% free, no API key -- EDGAR is public. Requires User-Agent header.
"""

from __future__ import annotations

import json
import logging
import time
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Top NQ movers by index weight
TARGET_TICKERS = {
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
    "AMZN": "0001018724",
    "META": "0001326801",
    "GOOGL": "0001652044",
    "TSLA": "0001318605",
    "AVGO": "0001649338",
    "NFLX": "0001065280",
    "AMD": "0000002488",
}

EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_BROWSE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"
EDGAR_HEADERS = {
    "User-Agent": "MNQ Trading Bot research@example.com",
    "Accept": "application/json, text/html",
}

CACHE_FILE = Path(__file__).resolve().parent / "insider_cache.json"
CACHE_TTL = 86400  # 24 hours


@dataclass
class InsiderFiling:
    ticker: str
    insider_name: str
    title: str              # CEO, CFO, Director, etc.
    transaction_type: str   # "P" (purchase) | "S" (sale)
    shares: int
    price: float
    date: str
    url: str = ""


@dataclass
class InsiderSignal:
    cluster_buys: list[str] = field(default_factory=list)
    cluster_sells: list[str] = field(default_factory=list)
    net_bias: str = "NEUTRAL"   # "BULLISH" | "BEARISH" | "NEUTRAL"
    total_buys: int = 0
    total_sells: int = 0
    filings: list[InsiderFiling] = field(default_factory=list)
    timestamp: float = 0.0


_cache: Optional[InsiderSignal] = None
_cache_ts: float = 0.0
_cache_lock = threading.Lock()


def fetch_insider_signal() -> InsiderSignal:
    """Get insider filing signal. Returns cached if fresh."""
    global _cache, _cache_ts
    with _cache_lock:
        if _cache and (time.time() - _cache_ts) < CACHE_TTL:
            return _cache

    # Try disk cache first
    signal = _load_disk_cache()
    if signal is None:
        try:
            signal = _scrape_insider_filings()
        except Exception as e:
            logger.warning("Insider filing scan failed: %s", e)
            signal = InsiderSignal(timestamp=time.time())

    with _cache_lock:
        _cache = signal
        _cache_ts = time.time()
    return signal


def _load_disk_cache() -> InsiderSignal | None:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - data.get("timestamp", 0) < CACHE_TTL:
                filings = [InsiderFiling(**f) for f in data.get("filings", [])]
                return InsiderSignal(
                    cluster_buys=data.get("cluster_buys", []),
                    cluster_sells=data.get("cluster_sells", []),
                    net_bias=data.get("net_bias", "NEUTRAL"),
                    total_buys=data.get("total_buys", 0),
                    total_sells=data.get("total_sells", 0),
                    filings=filings,
                    timestamp=data["timestamp"],
                )
    except Exception as e:
        logger.debug("Insider cache load failed: %s", e)
    return None


def _save_disk_cache(signal: InsiderSignal) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "cluster_buys": signal.cluster_buys,
            "cluster_sells": signal.cluster_sells,
            "net_bias": signal.net_bias,
            "total_buys": signal.total_buys,
            "total_sells": signal.total_sells,
            "filings": [
                {"ticker": f.ticker, "insider_name": f.insider_name,
                 "title": f.title, "transaction_type": f.transaction_type,
                 "shares": f.shares, "price": f.price, "date": f.date, "url": f.url}
                for f in signal.filings
            ],
            "timestamp": signal.timestamp,
        }
        CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("Insider cache save failed: %s", e)


def _scrape_insider_filings() -> InsiderSignal:
    """Scrape SEC EDGAR for Form 4 filings from target companies."""
    all_filings: list[InsiderFiling] = []
    lookback_days = 7

    for ticker, cik in TARGET_TICKERS.items():
        try:
            filings = _fetch_form4_for_company(ticker, cik, lookback_days)
            all_filings.extend(filings)
            time.sleep(0.2)  # respect EDGAR rate limits (10 req/sec)
        except Exception as e:
            logger.debug("Form 4 fetch failed for %s: %s", ticker, e)

    # Analyze: cluster buying/selling
    buy_counts: dict[str, int] = {}
    sell_counts: dict[str, int] = {}
    for f in all_filings:
        if f.transaction_type == "P":
            buy_counts[f.ticker] = buy_counts.get(f.ticker, 0) + 1
        elif f.transaction_type == "S":
            sell_counts[f.ticker] = sell_counts.get(f.ticker, 0) + 1

    # Cluster = 2+ insiders in same stock
    cluster_buys = [t for t, c in buy_counts.items() if c >= 2]
    cluster_sells = [t for t, c in sell_counts.items() if c >= 2]

    total_buys = sum(buy_counts.values())
    total_sells = sum(sell_counts.values())

    if cluster_buys and not cluster_sells:
        net_bias = "BULLISH"
    elif cluster_sells and not cluster_buys:
        net_bias = "BEARISH"
    elif total_buys > total_sells * 1.5:
        net_bias = "BULLISH"
    elif total_sells > total_buys * 1.5:
        net_bias = "BEARISH"
    else:
        net_bias = "NEUTRAL"

    logger.info("Insider filings: %s | buys=%d sells=%d cluster_buy=%s cluster_sell=%s",
                net_bias, total_buys, total_sells, cluster_buys, cluster_sells)

    signal = InsiderSignal(
        cluster_buys=cluster_buys,
        cluster_sells=cluster_sells,
        net_bias=net_bias,
        total_buys=total_buys,
        total_sells=total_sells,
        filings=all_filings[:50],
        timestamp=time.time(),
    )
    _save_disk_cache(signal)
    return signal


def _fetch_form4_for_company(ticker: str, cik: str, lookback_days: int) -> list[InsiderFiling]:
    """Fetch recent Form 4 filings for a company from EDGAR."""
    filings: list[InsiderFiling] = []

    url = EDGAR_BROWSE_URL
    params = {
        "action": "getcompany",
        "CIK": cik,
        "type": "4",
        "dateb": "",
        "owner": "only",
        "count": "20",
        "output": "atom",
    }

    try:
        resp = requests.get(url, params=params, headers=EDGAR_HEADERS, timeout=10)
        if resp.status_code != 200:
            return filings
    except Exception:
        return filings

    cutoff = datetime.now() - timedelta(days=lookback_days)

    try:
        soup = BeautifulSoup(resp.text, "html.parser")
        entries = soup.find_all("entry")

        for entry in entries[:20]:
            try:
                updated = entry.find("updated")
                if updated:
                    date_str = updated.text[:10]
                    filing_date = datetime.strptime(date_str, "%Y-%m-%d")
                    if filing_date < cutoff:
                        continue
                else:
                    date_str = ""

                title_elem = entry.find("title")
                title_text = title_elem.text if title_elem else ""

                link_elem = entry.find("link")
                filing_url = link_elem.get("href", "") if link_elem else ""

                # Parse title: "4 - [InsiderName] (0001234)"
                insider_name = ""
                if " - " in title_text:
                    parts = title_text.split(" - ", 1)
                    if len(parts) > 1:
                        insider_name = parts[1].split("(")[0].strip()

                # Determine transaction type from filing detail (simplified)
                # We'll mark as purchase/sale based on further parsing if possible
                tx_type = "P" if "purchase" in title_text.lower() else "S"

                filings.append(InsiderFiling(
                    ticker=ticker,
                    insider_name=insider_name,
                    title="Insider",
                    transaction_type=tx_type,
                    shares=0,
                    price=0.0,
                    date=date_str,
                    url=filing_url,
                ))
            except Exception:
                continue
    except Exception as e:
        logger.debug("EDGAR parse error for %s: %s", ticker, e)

    return filings
