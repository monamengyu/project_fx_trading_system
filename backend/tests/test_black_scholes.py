"""Unit tests for Garman-Kohlhagen FX option pricing."""

import math
from datetime import date

import pytest

from app.schemas.instrument_details import OptionDetails
from app.services.pricing.black_scholes import (
    normal_cdf,
    price_call,
    price_option,
    price_put,
)
from app.services.pricing.option_pricer import price_option_details

# Reference vector (validated against an independent Bloomberg Black-Scholes evaluation).
REF = {
    "S": 1.20,
    "K": 1.20,
    "rd": 0.02,
    "rf": 0.01,
    "tenor": 1.0,
    "vol": 0.20,
}
REF_CALL = 0.1001767779 
REF_PUT = 0.0883716121 
REF_CALL_DELTA = 0.5539755249 
REF_PUT_DELTA = -0.4359873515 
REF_GAMMA = 1.95271837 
REF_VEGA = 0.46862841 


def test_normal_cdf_bounds_and_center():
    assert normal_cdf(-10) == pytest.approx(0.0, abs=1e-12)
    assert normal_cdf(0) == pytest.approx(0.5)
    assert normal_cdf(10) == pytest.approx(1.0, abs=1e-12)


def test_reference_call_price():
    price = price_call(REF["S"], REF["K"], REF["rd"], REF["rf"], REF["tenor"], REF["vol"])
    assert price == pytest.approx(REF_CALL, abs=1e-4)


def test_reference_put_price():
    price = price_put(REF["S"], REF["K"], REF["rd"], REF["rf"], REF["tenor"], REF["vol"])
    assert price == pytest.approx(REF_PUT, abs=1e-4)


def test_put_call_parity():
    call = price_call(REF["S"], REF["K"], REF["rd"], REF["rf"], REF["tenor"], REF["vol"])
    put = price_put(REF["S"], REF["K"], REF["rd"], REF["rf"], REF["tenor"], REF["vol"])
    expected = REF["S"] * math.exp(-REF["rf"] * REF["tenor"]) - REF["K"] * math.exp(
        -REF["rd"] * REF["tenor"]
    )
    assert call - put == pytest.approx(expected, abs=1e-4)


def test_call_premium_greater_than_put_when_rd_gt_rf():
    call = price_call(1.0, 1.0, 0.05, 0.0, 1.0, 0.1)
    put = price_put(1.0, 1.0, 0.05, 0.0, 1.0, 0.1)
    assert call > put


def test_zero_tenor_returns_intrinsic_value():
    assert price_call(1.2, 1.0, 0.0, 0.0, 0.0, 0.2) == pytest.approx(0.2)
    assert price_put(1.0, 1.2, 0.0, 0.0, 0.0, 0.2) == pytest.approx(0.2)
    assert price_call(1.0, 1.2, 0.0, 0.0, 0.0, 0.2) == pytest.approx(0.0)


def test_zero_vol_returns_discounted_intrinsic_value():
    assert price_call(1.2, 1.0, 0.0, 0.0, 1.0, 0.0) == pytest.approx(0.2)
    assert price_put(1.0, 1.2, 0.0, 0.0, 1.0, 0.0) == pytest.approx(0.2)


def test_higher_vol_increases_premium():
    low = price_call(1.0, 1.0, 0.0, 0.0, 1.0, 0.05)
    high = price_call(1.0, 1.0, 0.0, 0.0, 1.0, 0.30)
    assert high > low


def test_deep_itm_delta_tends_to_bounds():
    call = price_option("CALL", 2.0, 1.0, 0.0, 0.0, 0.5, 0.2)
    put = price_option("PUT", 0.5, 1.0, 0.0, 0.0, 0.5, 0.2)
    assert call.delta == pytest.approx(1.0, abs=1e-6)
    assert call.premium == pytest.approx(1.0, abs=1e-6)
    assert put.delta == pytest.approx(-1.0, abs=1e-6)


def test_deep_otm_premium_vanishes():
    assert price_call(0.1, 10.0, 0.0, 0.0, 0.5, 0.2) == pytest.approx(0.0, abs=1e-12)
    assert price_put(10.0, 0.1, 0.0, 0.0, 0.5, 0.2) == pytest.approx(0.0, abs=1e-12)


def test_reference_greeks():
    call = price_option("CALL", REF["S"], REF["K"], REF["rd"], REF["rf"], REF["tenor"], REF["vol"])
    put = price_option("PUT", REF["S"], REF["K"], REF["rd"], REF["rf"], REF["tenor"], REF["vol"])
    assert call.delta == pytest.approx(REF_CALL_DELTA, abs=1e-4)
    assert put.delta == pytest.approx(REF_PUT_DELTA, abs=1e-4)
    assert call.gamma == pytest.approx(REF_GAMMA, abs=1e-4)
    assert call.vega == pytest.approx(REF_VEGA, abs=1e-4)


def test_greeks_signs_and_bounds():
    call = price_option("CALL", 1.0, 1.0, 0.0, 0.0, 1.0, 0.2)
    put = price_option("PUT", 1.0, 1.0, 0.0, 0.0, 1.0, 0.2)
    assert 0.0 <= call.delta <= 1.0
    assert -1.0 <= put.delta <= 0.0
    assert call.gamma == pytest.approx(put.gamma)
    assert call.vega == pytest.approx(put.vega)
    assert call.gamma > 0
    assert call.vega > 0
    assert call.theta < 0
    assert put.theta < 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"S": 0.0},
        {"S": -1.0},
        {"K": 0.0},
        {"K": -1.0},
        {"vol": -0.1},
        {"tenor": -1.0},
    ],
)
def test_invalid_inputs_raise(kwargs):
    args = {"S": 1.0, "K": 1.0, "rd": 0.0, "rf": 0.0, "tenor": 1.0, "vol": 0.2}
    args.update(kwargs)
    with pytest.raises(ValueError):
        price_call(**args)


def test_invalid_option_type_raises():
    with pytest.raises(ValueError):
        price_option("STRADDLE", 1.0, 1.0, 0.0, 0.0, 1.0, 0.2)


def _option_details(option_type="CALL", **overrides) -> OptionDetails:
    base = dict(
        instrument_type="OPTION",
        option_type=option_type,
        strike_rate=1.20,
        premium_date=date(2026, 7, 30),
        expiry_date=date(2027, 7, 30),
        delivery_date=date(2027, 8, 2),
        premium=0.0,
        premium_currency="USD",
        exercise_style="EUROPEAN",
    )
    base.update(overrides)
    return OptionDetails(**base)


def test_price_option_details_computes_tenor_and_result():
    details = _option_details(expiry_date=date(2027, 7, 30))
    result = price_option_details(
        details,
        spot=1.20,
        domestic_rate=0.02,
        foreign_rate=0.01,
        vol=0.20,
        valuation_date=date(2026, 7, 30),
    )
    assert result.tenor_years == pytest.approx(365.0 / 365.0)
    assert result.premium == pytest.approx(REF_CALL, abs=1e-4)
    assert result.premium_currency == "USD"
    assert result.greeks.delta == pytest.approx(REF_CALL_DELTA, abs=1e-4)


def test_price_option_details_defaults_to_today():
    details = _option_details(option_type="PUT")
    result = price_option_details(details, spot=1.20)
    assert result.valuation_date == date.today()
    assert result.premium_currency == "USD"
    assert result.greeks.delta <= 0


def test_price_option_details_rejects_expired_option():
    details = _option_details(expiry_date=date(2026, 1, 1))
    with pytest.raises(ValueError):
        price_option_details(details, spot=1.20, valuation_date=date(2026, 7, 30))
