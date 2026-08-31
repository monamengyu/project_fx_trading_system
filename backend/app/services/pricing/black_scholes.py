"""Garman-Kohlhagen pricing for European FX options.

Garman-Kohlhagen is the Black-Scholes model specialised to currency pairs:
the underlying is the spot exchange rate, so the foreign interest rate enters
as a continuous dividend yield.

Notation
--------
S  spot exchange rate (units of quote currency per base currency)
K  strike rate
rd domestic (base) interest rate, continuously compounded
rf foreign (quote) interest rate, continuously compounded
tenor time to expiry in years
vol volatility of the spot rate

Prices are returned in quote-currency units per unit of base currency.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

OptionType = Literal["CALL", "PUT"]

_TINY = 1e-10


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def normal_pdf(x: float) -> float:
    """Standard normal probability density function."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _validate_inputs(S: float, K: float, vol: float, tenor: float) -> None:
    if S <= 0:
        raise ValueError("Spot rate must be positive")
    if K <= 0:
        raise ValueError("Strike rate must be positive")
    if vol < 0:
        raise ValueError("vol cannot be negative")
    if tenor < 0:
        raise ValueError("Time to expiry cannot be negative")


def _d1_d2(S: float, K: float, rd: float, rf: float, tenor: float, vol: float) -> tuple[float, float]:
    """Garman-Kohlhagen d1/d2 (vol > 0, tenor > 0 expected)."""
    vol_sqrt_tenor = vol * math.sqrt(tenor)
    d1 = (math.log(S / K) + (rd - rf + 0.5 * vol * vol) * tenor) / vol_sqrt_tenor
    d2 = d1 - vol_sqrt_tenor
    return d1, d2


def price_call(S: float, K: float, rd: float, rf: float, tenor: float, vol: float) -> float:
    """Price of a European call option (Garman-Kohlhagen)."""
    _validate_inputs(S, K, vol, tenor)
    if vol <= _TINY or tenor <= _TINY:
        # Discounted intrinsic value when there is no time value.
        return max(S * math.exp(-rf * tenor) - K * math.exp(-rd * tenor), 0.0)
    d1, d2 = _d1_d2(S, K, rd, rf, tenor, vol)
    return S * math.exp(-rf * tenor) * normal_cdf(d1) - K * math.exp(-rd * tenor) * normal_cdf(d2)


def price_put(S: float, K: float, rd: float, rf: float, tenor: float, vol: float) -> float:
    """Price of a European put option (Garman-Kohlhagen)."""
    _validate_inputs(S, K, vol, tenor)
    if vol <= _TINY or tenor <= _TINY:
        return max(K * math.exp(-rd * tenor) - S * math.exp(-rf * tenor), 0.0)
    d1, d2 = _d1_d2(S, K, rd, rf, tenor, vol)
    return K * math.exp(-rd * tenor) * normal_cdf(-d2) - S * math.exp(-rf * tenor) * normal_cdf(-d1)


@dataclass(frozen=True)
class OptionPrice:
    """Garman-Kohlhagen price and standard greeks for one option.

    Greeks use the usual convention: vega and rho are per one-unit change in
    vol / rate (not per 1%), theta is per year.
    """

    option_type: OptionType
    premium: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


def price_option(
    option_type: OptionType,
    S: float,
    K: float,
    rd: float,
    rf: float,
    tenor: float,
    vol: float,
) -> OptionPrice:
    """Return the price and greeks of a European FX option."""
    _validate_inputs(S, K, vol, tenor)
    if option_type not in ("CALL", "PUT"):
        raise ValueError("option_type must be CALL or PUT")

    if vol <= _TINY or tenor <= _TINY:
        return _intrinsic_price(option_type, S, K, rd, rf, tenor)

    d1, d2 = _d1_d2(S, K, rd, rf, tenor, vol)
    disc_S = S * math.exp(-rf * tenor)
    disc_K = K * math.exp(-rd * tenor)
    phi_d1 = normal_pdf(d1)
    sqrt_tenor = math.sqrt(tenor)

    if option_type == "CALL":
        premium = disc_S * normal_cdf(d1) - disc_K * normal_cdf(d2)
        delta = math.exp(-rf * tenor) * normal_cdf(d1)
        theta = -(
            disc_S * phi_d1 * vol / (2.0 * sqrt_tenor)
            + rf * disc_S * normal_cdf(d1)
            - rd * disc_K * normal_cdf(d2)
        )
        rho = disc_K * tenor * normal_cdf(d2)
    else:
        premium = disc_K * normal_cdf(-d2) - disc_S * normal_cdf(-d1)
        delta = math.exp(-rf * tenor) * (normal_cdf(d1) - 1.0)
        theta = -(
            disc_S * phi_d1 * vol / (2.0 * sqrt_tenor)
            - rf * disc_S * normal_cdf(-d1)
            + rd * disc_K * normal_cdf(-d2)
        )
        rho = -disc_K * tenor * normal_cdf(-d2)

    gamma = disc_S * phi_d1 / (S * vol * sqrt_tenor)
    vega = disc_S * phi_d1 * sqrt_tenor

    return OptionPrice(
        option_type=option_type,
        premium=premium,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        rho=rho,
    )


def _intrinsic_price(
    option_type: OptionType, S: float, K: float, rd: float, rf: float, tenor: float
) -> OptionPrice:
    """Price/greeks in the degenerate vol=0 or tenor=0 case."""
    disc_S = S * math.exp(-rf * tenor)
    disc_K = K * math.exp(-rd * tenor)
    if option_type == "CALL":
        premium = max(disc_S - disc_K, 0.0)
        delta = 1.0 if disc_S > disc_K else 0.0
    else:
        premium = max(disc_K - disc_S, 0.0)
        delta = -1.0 if disc_K > disc_S else 0.0
    return OptionPrice(
        option_type=option_type,
        premium=premium,
        delta=delta,
        gamma=0.0,
        vega=0.0,
        theta=0.0,
        rho=0.0,
    )
