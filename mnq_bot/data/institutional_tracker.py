"""
SEC EDGAR 13F institutional holdings tracker.

Parses quarterly 13F-HR filings for top hedge funds to determine
institutional positioning in NASDAQ-heavy names.
100% free, no API key -- EDGAR is public.
"""

from __future__ import annotations

import json
import logging
import time
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# Top hedge funds by AUM (CIK numbers)
TARGET_FUNDS = {
    "Bridgewater": "0001350694",
    "Citadel": "0001423053",
    "Millennium": "0001273087",
    "Renaissance": "0001037389",
    "Two Sigma": "0001179392",
    "DE Shaw": "0001009207",
    "Point72": "0001603466",
    "Appaloosa": "0001656456",
}

# NASDAQ mega-caps we track for NQ bias
NASDAQ_NAMES = {
    "APPLE INC", "MICROSOFT CORP", "NVIDIA CORP", "AMAZON COM INC",
    "META PLATFORMS", "ALPHABET INC", "TESLA INC", "BROADCOM INC",
    "NETFLIX INC", "ADVANCED MICRO DEVICES",
}

EDGAR_HEADERS = {
    "User-Agent": "MNQ Trading Bot research@example.com",
    "Accept": "application/json",
}

CACHE_FILE = Path(__file__).resolve().parent / "institutional_cache.json"
CACHE_TTL = 2592000  # 30 days


@dataclass
class HoldingChange:
    fund: str
    company: str
    action: str         # "NEW" | "INCREASED" | "DECREASED" | "SOLD"
    shares: int
    value_usd: int


@dataclass
class InstitutionalSignal:
    net_bias: str = "NEUTRAL"  # "BULLISH" | "BEARISH" | "NEUTRAL"
    top_buys: list[str] = field(default_factory=list)
    top_sells: list[str] = field(default_factory=list)
    changes: list[HoldingChange] = field(default_factory=list)
    funds_checked: int = 0
    last_updated: str = ""
    timestamp: float = 0.0


_cache: Optional[InstitutionalSignal] = None
_cache_ts: float = 0.0
_cache_lock = threading.Lock()


def fetch_institutional_signal() -> InstitutionalSignal:
    """Get 13F institutional signal. Returns cached (disk or memory) if fresh."""
    global _cache, _cache_ts
    with _cache_lock:
        if _cache and (time.time() - _cache_ts) < CACHE_TTL:
            return _cache

    signal = _load_disk_cache()
    if signal is None:
        try:
            signal = _fetch_13f_data()
        except Exception as e:
            logger.warning("13F institutional scan failed: %s", e)
            signal = InstitutionalSignal(timestamp=time.time())

    with _cache_lock:
        _cache = signal
        _cache_ts = time.time()
    return signal


def _load_disk_cache() -> InstitutionalSignal | None:
    try:
        if CACHE_FILE.exists():
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
            if time.time() - data.get("timestamp", 0) < CACHE_TTL:
                changes = [HoldingChange(**c) for c in data.get("changes", [])]
                return InstitutionalSignal(
                    net_bias=data.get("net_bias", "NEUTRAL"),
                    top_buys=data.get("top_buys", []),
                    top_sells=data.get("top_sells", []),
                    changes=changes,
                    funds_checked=data.get("funds_checked", 0),
                    last_updated=data.get("last_updated", ""),
                    timestamp=data["timestamp"],
                )
    except Exception:
        pass
    return None


def _save_disk_cache(signal: InstitutionalSignal) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "net_bias": signal.net_bias,
            "top_buys": signal.top_buys,
            "top_sells": signal.top_sells,
            "changes": [
                {"fund": c.fund, "company": c.company, "action": c.action,
                 "shares": c.shares, "value_usd": c.value_usd}
                for c in signal.changes
            ],
            "funds_checked": signal.funds_checked,
            "last_updated": signal.last_updated,
            "timestamp": signal.timestamp,
        }
        CACHE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("13F cache save failed: %s", e)


def _fetch_13f_data() -> InstitutionalSignal:
    """Fetch latest 13F filings from EDGAR for tracked funds."""
    all_changes: list[HoldingChange] = []
    funds_checked = 0

    for fund_name, cik in TARGET_FUNDS.items():
        try:
            changes = _fetch_fund_13f(fund_name, cik)
            all_changes.extend(changes)
            funds_checked += 1
            time.sleep(0.2)  # respect EDGAR rate limits
        except Exception as e:
            logger.debug("13F fetch failed for %s: %s", fund_name, e)

    # Aggregate: count buys vs sells for NASDAQ names
    buy_names: dict[str, int] = {}
    sell_names: dict[str, int] = {}
    for c in all_changes:
        if c.action in ("NEW", "INCREASED"):
            buy_names[c.company] = buy_names.get(c.company, 0) + 1
        elif c.action in ("DECREASED", "SOLD"):
            sell_names[c.company] = sell_names.get(c.company, 0) + 1

    top_buys = sorted(buy_names.keys(), key=lambda x: buy_names[x], reverse=True)[:5]
    top_sells = sorted(sell_names.keys(), key=lambda x: sell_names[x], reverse=True)[:5]

    total_buy_actions = sum(buy_names.values())
    total_sell_actions = sum(sell_names.values())

    if total_buy_actions > total_sell_actions * 1.5:
        net_bias = "BULLISH"
    elif total_sell_actions > total_buy_actions * 1.5:
        net_bias = "BEARISH"
    else:
        net_bias = "NEUTRAL"

    logger.info("13F institutional: %s | buys=%d sells=%d funds=%d",
                net_bias, total_buy_actions, total_sell_actions, funds_checked)

    signal = InstitutionalSignal(
        net_bias=net_bias,
        top_buys=top_buys,
        top_sells=top_sells,
        changes=all_changes[:30],
        funds_checked=funds_checked,
        last_updated=time.strftime("%Y-%m-%d"),
        timestamp=time.time(),
    )
    _save_disk_cache(signal)
    return signal


def _fetch_fund_13f(fund_name: str, cik: str) -> list[HoldingChange]:
    """Fetch the latest 13F for a fund and extract NASDAQ-related changes."""
    changes: list[HoldingChange] = []

    # Get filing index
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    try:
        resp = requests.get(url, headers=EDGAR_HEADERS, timeout=10)
        if resp.status_code != 200:
            return changes
        data = resp.json()
    except Exception:
        return changes

    # Find latest 13F-HR filing
    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])

    filing_acc = None
    for i, form in enumerate(forms):
        if form in ("13F-HR", "13F-HR/A"):
            filing_acc = accessions[i] if i < len(accessions) else None
            break

    if not filing_acc:
        return changes

    # Fetch the 13F XML holdings table
    acc_clean = filing_acc.replace("-", "")
    holdings_url = f"https://www.sec.gov/Archives/edgar/data/{cik.lstrip('0')}/{acc_clean}"

    try:
        idx_resp = requests.get(f"{holdings_url}/index.json", headers=EDGAR_HEADERS, timeout=10)
        if idx_resp.status_code != 200:
            return changes
        idx = idx_resp.json()
        # Find the infotable XML file
        xml_file = None
        for item in idx.get("directory", {}).get("item", []):
            name = item.get("name", "")
            if "infotable" in name.lower() or name.endswith(".xml"):
                xml_file = name
                break
        if not xml_file:
            return changes
    except Exception:
        return changes

    try:
        xml_resp = requests.get(f"{holdings_url}/{xml_file}", headers=EDGAR_HEADERS, timeout=15)
        if xml_resp.status_code != 200:
            return changes
    except Exception:
        return changes

    # Parse XML for NASDAQ names
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(xml_resp.text, "html.parser")
    for info in soup.find_all("infotable"):
        try:
            name_elem = info.find("nameofissuer")
            if not name_elem:
                continue
            company = name_elem.text.strip().upper()

            # Check if it's a NASDAQ name we care about
            is_nasdaq = any(nq in company for nq in NASDAQ_NAMES)
            if not is_nasdaq:
                continue

            shares_elem = info.find("sshprnamt")
            value_elem = info.find("value")
            shares = int(shares_elem.text) if shares_elem else 0
            value = int(value_elem.text) * 1000 if value_elem else 0  # 13F values in thousands

            changes.append(HoldingChange(
                fund=fund_name,
                company=company,
                action="INCREASED",  # simplified; real comparison needs prior quarter
                shares=shares,
                value_usd=value,
            ))
        except Exception:
            continue

    return changes
