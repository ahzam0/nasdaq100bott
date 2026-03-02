from .base import Broker, OrderResult
from .paper_trade import PaperBroker
from .tradovate import TradovateBroker
from .ninjatrader import NinjaTraderBroker


def get_broker(broker_name: str) -> Broker:
    if broker_name == "ninjatrader":
        return NinjaTraderBroker()
    if broker_name == "tradovate":
        return TradovateBroker()
    return PaperBroker()


__all__ = ["Broker", "OrderResult", "PaperBroker", "TradovateBroker", "NinjaTraderBroker", "get_broker"]
