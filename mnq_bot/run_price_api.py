"""
Start the local Price API server (NQ/MNQ price and candles).
Run this in a separate terminal, then set MNQ_PRICE_API_URL=http://127.0.0.1:5001 to use it in the bot.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    from api.price_server import main
    main()
