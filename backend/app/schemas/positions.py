from pydantic import BaseModel


class PositionRead(BaseModel):
    currency_pair: str
    currency_1: str
    currency_2: str
    total_notional_1: float
    total_notional_2: float | None = None
    net_notional_1: float
    net_notional_2: float | None = None
    # Net delta across all booked legs, expressed in units of currency_1.
    # Spot/forward legs contribute their signed notional; options contribute
    # their signed notional multiplied by the option's unit delta.
    delta: float | None = None
    # Net gamma/vega/theta across option legs (spot/forward legs contribute
    # zero). Null when option legs cannot be priced (e.g. live rate missing).
    gamma: float | None = None
    vega: float | None = None
    theta: float | None = None
    # Unrealised P&L of the net position in USD: current market value minus
    # the executed (booked) value, converted to USD. Null if unavailable.
    mtm_value: float | None = None
