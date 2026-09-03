"""FX-aware wrapper around the Garman-Kohlhagen model.

The public helpers adapt raw option terms or a booked
:class:`~app.schemas.instrument_details.OptionDetails` trade to the core
pricing math: they derive time-to-expiry from the expiry date and return a
structured result (premium plus greeks) that the pricing REST endpoints can
return directly.
"""

from __future__ import annotations

from datetime import date

from app.schemas.instrument_details import OptionDetails
from app.services.pricing.black_scholes import OptionPrice, price_option
from app.services.pricing.schemas import OptionGreeks, OptionPriceResult

DAYS_PER_YEAR = 365.0


def _price(
    option_type: str,
    spot: float,
    strike_rate: float,
    expiry_date: date,
    domestic_rate: float,
    foreign_rate: float,
    vol: float,
    valuation_date: date,
    premium_currency: str,
) -> OptionPriceResult:
    """Shared core: validate the expiry, derive tenor and run the model."""
    if expiry_date < valuation_date:
        raise ValueError("Option has already expired")

    tenor = (expiry_date - valuation_date).days / DAYS_PER_YEAR
    price: OptionPrice = price_option(
        option_type,
        S=spot,
        K=strike_rate,
        rd=domestic_rate,
        rf=foreign_rate,
        tenor=tenor,
        vol=vol,
    )

    return OptionPriceResult(
        option_type=option_type,
        premium=price.premium,
        premium_currency=premium_currency,
        spot=spot,
        strike_rate=strike_rate,
        valuation_date=valuation_date,
        expiry_date=expiry_date,
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
    return _price(
        details.option_type,
        spot=spot,
        strike_rate=details.strike_rate,
        expiry_date=details.expiry_date,
        domestic_rate=domestic_rate,
        foreign_rate=foreign_rate,
        vol=vol,
        valuation_date=valuation_date or date.today(),
        premium_currency=details.premium_currency,
    )


def price_option_quote(
    option_type: str,
    spot: float,
    strike_rate: float,
    expiry_date: date,
    domestic_rate: float = 0.0,
    foreign_rate: float = 0.0,
    vol: float = 0.10,
    valuation_date: date | None = None,
    premium_currency: str = "",
) -> OptionPriceResult:
    """Price raw option terms (a live quote), with no booked trade required.

    ``premium_currency`` is informational only (the per-unit premium is always
    denominated in the quote currency of the pair); pass it to tag the result.
    """
    return _price(
        option_type,
        spot=spot,
        strike_rate=strike_rate,
        expiry_date=expiry_date,
        domestic_rate=domestic_rate,
        foreign_rate=foreign_rate,
        vol=vol,
        valuation_date=valuation_date or date.today(),
        premium_currency=premium_currency,
    )
