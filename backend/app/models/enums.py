import enum


class InstrumentType(str, enum.Enum):
    SPOT = "SPOT"
    FORWARD = "FORWARD"
    OPTION = "OPTION"


class CurrencyPair(str, enum.Enum):
    EURUSD = "EURUSD"
    GBPUSD = "GBPUSD"
    USDJPY = "USDJPY"


class Direction(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class Currency(str, enum.Enum):
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"
    JPY = "JPY"


class TradeStatus(str, enum.Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    MATURED = "MATURED"


class TradeState(str, enum.Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    BOOKED = "BOOKED"
    AMENDED = "AMENDED"
    CANCELLED = "CANCELLED"
    MATURED = "MATURED"

