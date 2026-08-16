from pydantic import BaseModel


class PositionRead(BaseModel):
    currency_pair: str
    currency_1: str
    currency_2: str
    count: int
    total_notional_1: float
    total_notional_2: float | None = None
    net_notional_1: float
    net_notional_2: float | None = None
    # Mark-to-market value of the net position in currency_2, using the
    # current market rate. Null if the rate is unavailable.
    mtm_value: float | None = None
