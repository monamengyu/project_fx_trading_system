import { useEffect, useState } from "react";
import { useBookTrade } from "../hooks/useBookTrade.js";
import { useMarketRates } from "../hooks/useMarketRates.js";
import { spotValueDate, toISODate, todayISO } from "../utils/date.js";

const PAIRS = ["EURUSD", "GBPUSD", "USDJPY"];
const DIRECTIONS = ["BUY", "SELL"];
const COUNTERPARTIES = ["BANK_A", "BANK_B", "BANK_C"];
const INSTRUMENT_TYPES = ["SPOT", "FORWARD"];

// Today is always a business day (weekends roll forward); the spot value
// date is that date + 2 business days.
const TODAY = todayISO();
const SPOT_DATE = toISODate(spotValueDate(new Date(`${TODAY}T00:00:00`)));

const EMPTY_FORM = {
  instrument_type: "SPOT",
  currency_pair: "EURUSD",
  direction: "BUY",
  notional_1: "1000000",
  counterparty: "BANK_A",
  rate: "1.0850",
  settlement_date: SPOT_DATE,
};

function buildPayload(form) {
  const notional_1 = Number(form.notional_1);
  const rate = Number(form.rate);
  const type = form.instrument_type;
  return {
    instrument_type: type,
    currency_pair: form.currency_pair,
    direction: form.direction,
    currency_1: form.currency_pair.slice(0, 3),
    notional_1,
    currency_2: form.currency_pair.slice(3),
    notional_2: Math.round(notional_1 * rate * 100) / 100,
    counterparty: form.counterparty,
    comment: "",
    instrument_details: {
      instrument_type: type,
      rate,
      settlement_date: form.settlement_date,
    },
  };
}

function formatNumber(value) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function formatRate(value) {
  return Number(value).toFixed(4);
}

function validate(form) {
  const settlement = form.settlement_date;
  if (!settlement) return "Settlement date is required.";
  if (form.instrument_type === "SPOT") {
    if (settlement < TODAY) return `SPOT cannot settle before ${TODAY}.`;
    if (settlement > SPOT_DATE) {
      return `SPOT settles by ${SPOT_DATE} (today + 2 business days). For ${settlement} use FORWARD.`;
    }
  } else {
    if (settlement <= SPOT_DATE) {
      return `FORWARD must settle after ${SPOT_DATE} (today + 2 business days). For ${settlement} use SPOT.`;
    }
  }
  return null;
}

function suggestedType(form) {
  const s = form.settlement_date;
  if (form.instrument_type === "SPOT" && s > SPOT_DATE) return "FORWARD";
  if (form.instrument_type === "FORWARD" && s <= SPOT_DATE) return "SPOT";
  return null;
}

export function NewTradeForm({ onBooked }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const [review, setReview] = useState(null); // payload awaiting confirmation
  const [formError, setFormError] = useState(null);
  const [rateTouched, setRateTouched] = useState(false);
  const { submit, submitting, result, error } = useBookTrade();
  const { rates } = useMarketRates();

  // Default the rate to the latest market rate for the selected pair, unless
  // the user has manually overridden it.
  useEffect(() => {
    const entry = rates[form.currency_pair];
    if (entry?.rate != null && !rateTouched) {
      const market = formatRate(entry.rate);
      setForm((prev) => (prev.rate !== market ? { ...prev, rate: market } : prev));
    }
  }, [form.currency_pair, rates, rateTouched]);

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setFormError(null);
  }

  function handlePairChange(value) {
    setForm((prev) => ({ ...prev, currency_pair: value }));
    setRateTouched(false); // re-default to the new pair's market rate
    setFormError(null);
  }

  function handleRateChange(value) {
    setForm((prev) => ({ ...prev, rate: value }));
    setRateTouched(true); // don't overwrite a manually entered rate
    setFormError(null);
  }

  function handleReview(event) {
    event.preventDefault();
    const problem = validate(form);
    if (problem) {
      setFormError(problem);
      return;
    }
    setFormError(null);
    setReview(buildPayload(form));
  }

  function handleBack() {
    setReview(null);
  }

  async function handleConfirm() {
    const trade = await submit(review);
    if (trade) {
      setForm(EMPTY_FORM);
      setRateTouched(false);
      setReview(null);
      onBooked?.(trade);
    }
  }

  const suggest = suggestedType(form);

  if (review) {
    return (
      <div className="panel__body">
        <h2 className="panel__title">Confirm Trade</h2>
        <ul className="review">
          <li>
            <span>Type</span>
            <strong>{review.instrument_type}</strong>
          </li>
          <li>
            <span>Pair</span>
            <strong>{review.currency_pair}</strong>
          </li>
          <li>
            <span>Direction</span>
            <strong>{review.direction}</strong>
          </li>
          <li>
            <span>Notional</span>
            <strong>
              {formatNumber(review.notional_1)} {review.currency_1}
            </strong>
          </li>
          <li>
            <span>Rate</span>
            <strong>{review.instrument_details.rate}</strong>
          </li>
          <li>
            <span>Counter leg</span>
            <strong>
              {formatNumber(review.notional_2)} {review.currency_2}
            </strong>
          </li>
          <li>
            <span>Settlement</span>
            <strong>{review.instrument_details.settlement_date}</strong>
          </li>
          <li>
            <span>Counterparty</span>
            <strong>{review.counterparty}</strong>
          </li>
        </ul>
        {error && <p className="form__result form__result--error">{error}</p>}
        <div className="form__actions">
          <button className="btn btn--ghost" onClick={handleBack} disabled={submitting}>
            Back
          </button>
          <button
            className="btn btn--primary"
            onClick={handleConfirm}
            disabled={submitting}
          >
            {submitting ? "Booking…" : "Confirm & Book"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="panel__body">
      <h2 className="panel__title">New Trade</h2>
      <form className="form" onSubmit={handleReview}>
        <div className="form__row">
          <div className="field">
            <label className="field__label" htmlFor="instrument_type">
              Instrument Type
            </label>
            <select
              id="instrument_type"
              className="field__select"
              value={form.instrument_type}
              onChange={(e) => update("instrument_type", e.target.value)}
            >
              {INSTRUMENT_TYPES.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="currency_pair">
              Currency Pair
            </label>
            <select
              id="currency_pair"
              className="field__select"
              value={form.currency_pair}
              onChange={(e) => handlePairChange(e.target.value)}
            >
              {PAIRS.map((pair) => (
                <option key={pair} value={pair}>
                  {pair}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="form__row">
          <div className="field">
            <label className="field__label" htmlFor="direction">
              Direction
            </label>
            <select
              id="direction"
              className="field__select"
              value={form.direction}
              onChange={(e) => update("direction", e.target.value)}
            >
              {DIRECTIONS.map((direction) => (
                <option key={direction} value={direction}>
                  {direction}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field__label" htmlFor="counterparty">
              Counterparty
            </label>
            <select
              id="counterparty"
              className="field__select"
              value={form.counterparty}
              onChange={(e) => update("counterparty", e.target.value)}
            >
              {COUNTERPARTIES.map((counterparty) => (
                <option key={counterparty} value={counterparty}>
                  {counterparty}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="form__row">
          <div className="field">
            <label className="field__label" htmlFor="notional_1">
              Notional ({form.currency_pair.slice(0, 3)})
            </label>
            <input
              id="notional_1"
              className="field__input"
              type="number"
              min="0"
              step="1"
              value={form.notional_1}
              onChange={(e) => update("notional_1", e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label className="field__label" htmlFor="rate">
              Rate
            </label>
            <input
              id="rate"
              className="field__input"
              type="number"
              min="0"
              step="0.0001"
              value={form.rate}
              onChange={(e) => handleRateChange(e.target.value)}
              required
            />
          </div>
        </div>

        <div className="field">
          <label className="field__label" htmlFor="settlement_date">
            Settlement Date
          </label>
          <input
            id="settlement_date"
            className="field__input"
            type="date"
            value={form.settlement_date}
            onChange={(e) => update("settlement_date", e.target.value)}
            required
          />
          <p className="field__hint">
            SPOT settles by {SPOT_DATE}; later dates are FORWARD.
          </p>
        </div>

        {formError && (
          <p className="form__result form__result--error">
            {formError}
            {suggest && (
              <button
                type="button"
                className="btn btn--ghost form__switch"
                onClick={() => update("instrument_type", suggest)}
              >
                Switch to {suggest}
              </button>
            )}
          </p>
        )}
        {result && (
          <p className="form__result form__result--ok">
            Booked {result.currency_pair} {result.direction} ({result.status}) —
            {result.trade_id}
          </p>
        )}

        <button className="btn btn--primary" type="submit" disabled={submitting}>
          Review Trade
        </button>
      </form>
    </div>
  );
}
