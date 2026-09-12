import enum


class InstrumentType(str, enum.Enum):
    SPOT = "SPOT"
    FORWARD = "FORWARD"
    OPTION = "OPTION"


class CurrencyPair(str, enum.Enum):
    # Majors
    EURUSD = "EURUSD"
    GBPUSD = "GBPUSD"
    USDJPY = "USDJPY"
    USDCHF = "USDCHF"
    USDCAD = "USDCAD"
    AUDUSD = "AUDUSD"
    NZDUSD = "NZDUSD"
    # Other USD pairs
    USDCNH = "USDCNH"
    USDHKD = "USDHKD"
    USDSGD = "USDSGD"
    USDSEK = "USDSEK"
    USDNOK = "USDNOK"
    USDMXN = "USDMXN"
    USDZAR = "USDZAR"
    USDTRY = "USDTRY"


class Direction(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class Currency(str, enum.Enum):
    EUR = "EUR"
    USD = "USD"
    GBP = "GBP"
    JPY = "JPY"
    CHF = "CHF"
    CAD = "CAD"
    AUD = "AUD"
    NZD = "NZD"
    CNH = "CNH"
    HKD = "HKD"
    SGD = "SGD"
    SEK = "SEK"
    NOK = "NOK"
    MXN = "MXN"
    ZAR = "ZAR"
    TRY = "TRY"


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

