"""FX-aware wrapper around the Garman-Kohlhagen model.

``price_option_details`` adapts an :class:`~app.schemas.instrument_details.OptionDetails`
trade to the core pricing math: it derives time-to-expiry from the trade's
expiry date and returns a structured result (premium plus greeks) that the
pricing REST endpoints can return directly.
"""

from __future__ import annotations

from datetime import date

from app.schemas.instrument_details import OptionDetails
from app.services.pricing.black_scholes import OptionPrice, price_option
from app.services.pricing.schemas import OptionGreeks, OptionPriceResult

DAYS_PER_YEAR = 365.0


def price_option_details(
    details: OptionDetails,
    spot: float,
    domestic_rate: float = 0.0,
    foreign_rate: float = 0.0,
    vol: float = 0.10,
    valuation_date: date | None = None,
) -> OptionPriceResult:
    """Price an FX option trade under Garman-Kohlhagen.

    ``domestic_rate`` is the continuously compounded rate on the quote
    currency (the numeraire) and ``foreign_rate`` is the rate on the base
    currency (the underlying asset).

    Raises ``ValueError`` when the expiry falls strictly before the valuation
    date, or when a pricing input is invalid.
    """
    valuation_date = valuation_date or date.today()
    if details.expiry_date < valuation_date:
        raise ValueError("Option has already expired")

    tenor = (details.expiry_date - valuation_date).days / DAYS_PER_YEAR
    price: OptionPrice = price_option(
        details.option_type,
        S=spot,
        K=details.strike_rate,
        rd=domestic_rate,
        rf=foreign_rate,
        tenor=tenor,
        vol=vol,
    )

    return OptionPriceResult(
        option_type=details.option_type,
        premium=price.premium,
        premium_currency=details.premium_currency,
        spot=spot,
        strike_rate=details.strike_rate,
        valuation_date=valuation_date,
        expiry_date=details.expiry_date,
        tenor_years=tenor,
        vol=vol,
        domestic_rate=domestic_rate,
        foreign_rate=foreign_rate,
        greeks=OptionGreeks(
            delta=price.delta,
            gamma=price.gamma,
            vega=price.vega,
            theta=price.theta,
            rho=price.rho,
        ),
    )
