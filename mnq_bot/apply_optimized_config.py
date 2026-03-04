"""
Read optimized_config_snippet.txt and update config.py with those values.
Run after optimize_40pct.py finishes.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
SNIPPET = ROOT / "optimized_config_snippet.txt"
CONFIG = ROOT / "config.py"

# Keys we update (snippet name -> config.py variable name)
KEYS = [
    ("MIN_RR_RATIO", "MIN_RR_RATIO"),
    ("LEVEL_TOLERANCE_PTS", "LEVEL_TOLERANCE_PTS"),
    ("MAX_RISK_PTS", "MAX_RISK_PTS"),
    ("MAX_TRADES_PER_DAY", "MAX_TRADES_PER_DAY"),
    ("SKIP_FIRST_MINUTES", "SKIP_FIRST_MINUTES"),
    ("MIN_BODY_PTS", "MIN_BODY_PTS"),
    ("RETEST_ONLY", "RETEST_ONLY"),
    ("MAX_RISK_PER_TRADE_USD", "MAX_RISK_PER_TRADE_USD"),
]


def main():
    if not SNIPPET.exists():
        print(f"Missing {SNIPPET}. Run: python optimize_40pct.py --workers 1 --rounds 1 --combos 50 --months 3")
        return 1
    lines = SNIPPET.read_text(encoding="utf-8").strip().splitlines()
    # Parse KEY = value (skip comments)
    updates = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"([A-Z_]+)\s*=\s*(.+)", line)
        if m:
            key, value = m.group(1), m.group(2).strip()
            updates[key] = value

    if not updates:
        print("No key=value lines found in snippet.")
        return 1

    text = CONFIG.read_text(encoding="utf-8")
    for snippet_key, config_key in KEYS:
        if snippet_key not in updates:
            continue
        value = updates[snippet_key]
        # Match line like: MIN_RR_RATIO = 1.8   # comment
        pattern = re.compile(
            r"^(\s*" + re.escape(config_key) + r"\s*=\s*).*$",
            re.MULTILINE,
        )
        replacement = rf"\g<1>{value}"
        new_text, n = pattern.subn(replacement, text, count=1)
        if n:
            text = new_text
            print(f"  {config_key} = {value}")

    CONFIG.write_text(text, encoding="utf-8")
    print(f"Updated {CONFIG}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
