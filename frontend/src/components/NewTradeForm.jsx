import { useEffect, useState } from "react";
import { useBookTrade } from "../hooks/useBookTrade.js";
import { useMarketRates } from "../hooks/useMarketRates.js";
import { useSupportedPairs } from "../hooks/useSupportedPairs.js";
import { quoteOption } from "../services/pricing.js";
import {
  addBusinessDays,
  isBusinessDay,
  spotValueDate,
  toISODate,
  todayISO,
} from "../utils/date.js";

const DIRECTIONS = ["BUY", "SELL"];
const COUNTERPARTIES = ["BANK_A", "BANK_B", "BANK_C"];
const INSTRUMENT_TYPES = ["SPOT", "FORWARD", "OPTION"];
const OPTION_TYPES = ["CALL", "PUT"];
const EXERCISE_STYLES = ["EUROPEAN", "AMERICAN"];
const PREMIUM_CURRENCIES = ["USD", "EUR", "GBP", "JPY"];

// Today is always a business day (weekends roll forward); the spot value
// date is that date + 2 business days. Default option expiry is ~1 month out
// and delivery defaults to expiry + 2 business days.
const TODAY = todayISO();
const SPOT_DATE = toISODate(spotValueDate(new Date(`${TODAY}T00:00:00`)));
const OPTION_EXPIRY = toISODate(
  addBusinessDays(new Date(`${TODAY}T00:00:00`), 21),
);

// FX option delivery is the expiry date + 2 business days.
function deliveryDateFor(expiryISO) {
  return toISODate(
    addBusinessDays(new Date(`${expiryISO}T00:00:00`), 2),
  );
}

const OPTION_DELIVERY = deliveryDateFor(OPTION_EXPIRY);

const EMPTY_FORM = {
  instrument_type: "SPOT",
  currency_pair: "EURUSD",
  direction: "BUY",
  notional_1: "1,000,000",
  counterparty: "BANK_A",
  rate: "1.0850",
  settlement_date: SPOT_DATE,
  // OPTION
  option_type: "CALL",
  strike_rate: "1.0850",
  premium_date: SPOT_DATE,
  expiry_date: OPTION_EXPIRY,
  delivery_date: OPTION_DELIVERY,
  premium: "0",
  premium_currency: "USD",
  exercise_style: "EUROPEAN",
};

function buildPayload(form) {
  const notional_1 = toNumber(form.notional_1);
  const type = form.instrument_type;
  const isOption = type === "OPTION";
  const base = {
    instrument_type: type,
    currency_pair: form.currency_pair,
    direction: form.direction,
    currency_1: form.currency_pair.slice(0, 3),
    notional_1,
    currency_2: form.currency_pair.slice(3),
    counterparty: form.counterparty,
    comment: "",
  };
  if (isOption) {
    return {
      ...base,
      instrument_details: {
        instrument_type: "OPTION",
        option_type: form.option_type,
        strike_rate: toNumber(form.strike_rate),
        premium_date: form.premium_date,
        expiry_date: form.expiry_date,
        delivery_date: form.delivery_date,
        premium: toNumber(form.premium),
        premium_currency: form.premium_currency,
        exercise_style: form.exercise_style,
      },
    };
  }
  const rate = toNumber(form.rate);
  return {
    ...base,
    notional_2: Math.round(notional_1 * rate * 100) / 100,
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

// Strips grouping commas and converts a form value to a number (NaN-safe).
function toNumber(value) {
  if (value == null || value === "") return NaN;
  return Number(String(value).replace(/,/g, ""));
}

// Groups the integer part of a numeric string with thousands separators.
function formatInput(value) {
  if (value == null || value === "") return "";
  const s = String(value);
  const negative = s.startsWith("-");
  const unsigned = negative ? s.slice(1) : s;
  const dotIndex = unsigned.indexOf(".");
  const intPart = dotIndex === -1 ? unsigned : unsigned.slice(0, dotIndex);
  const fracPart = dotIndex === -1 ? "" : unsigned.slice(dotIndex + 1);
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "-" : ""}${grouped}${dotIndex === -1 ? "" : `.${fracPart}`}`;
}

// Maps a caret position in the raw (comma-free) input to the equivalent
// position in the comma-grouped value so grouping doesn't move the caret.
function cursorAfterCommas(formatted, raw, cursor) {
  let kept = 0;
  for (let i = 0; i < cursor && i < raw.length; i++) {
    if (raw[i] !== ",") kept++;
  }
  let pos = 0;
  while (pos < formatted.length && kept > 0) {
    if (formatted[pos] !== ",") kept--;
    pos++;
  }
  return pos;
}

function validate(form) {
  if (form.instrument_type === "OPTION") {
    if (!form.option_type) return "Option type (CALL/PUT) is required.";
    if (!form.strike_rate || toNumber(form.strike_rate) <= 0) {
      return "Strike rate is required and must be positive.";
    }
    for (const [label, value] of [
      ["Premium date", form.premium_date],
      ["Expiry date", form.expiry_date],
      ["Delivery date", form.delivery_date],
    ]) {
      if (!value) return `${label} is required.`;
      if (!isBusinessDay(new Date(`${value}T00:00:00`))) {
        return `${label} must be a business day (Mon-Fri).`;
      }
    }
    if (form.expiry_date < TODAY) return `Expiry date cannot be before ${TODAY}.`;
    if (form.delivery_date < form.expiry_date) {
      return "Delivery date cannot be before the expiry date.";
    }
    if (toNumber(form.premium) < 0) return "Premium cannot be negative.";
    return null;
  }
  const settlement = form.settlement_date;
  if (!settlement) return "Settlement date is required.";
  if (!isBusinessDay(new Date(`${settlement}T00:00:00`))) {
    return "Settlement date must be a business day (Mon-Fri).";
  }
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
  if (form.instrument_type === "OPTION") return null;
  const s = form.settlement_date;
  if (form.instrument_type === "SPOT" && s > SPOT_DATE) return "FORWARD";
  if (form.instrument_type === "FORWARD" && s <= SPOT_DATE) return "SPOT";
  return null;
}

export function NewTradeForm({ onBooked }) {
  const PAIRS = useSupportedPairs();
  const [form, setForm] = useState(EMPTY_FORM);
  const [review, setReview] = useState(null); // payload awaiting confirmation
  const [formError, setFormError] = useState(null);
  const [rateTouched, setRateTouched] = useState(false);
  const [strikeTouched, setStrikeTouched] = useState(false);
  const [deliveryTouched, setDeliveryTouched] = useState(false);
  const [premiumTouched, setPremiumTouched] = useState(false);
  const { submit, submitting, result, error } = useBookTrade();
  const { rates } = useMarketRates();

  // Default the rate to the latest market rate for the selected pair, unless
  // the user has manually overridden it. The strike follows the same market
  // default for OPTION trades.
  useEffect(() => {
    const entry = rates[form.currency_pair];
    if (entry?.rate == null) return;
    const market = formatRate(entry.rate);
    setForm((prev) => {
      const next = { ...prev };
      if (!rateTouched && prev.rate !== market) next.rate = market;
      if (!strikeTouched && prev.strike_rate !== market) next.strike_rate = market;
      return next;
    });
  }, [form.currency_pair, rates, rateTouched, strikeTouched]);

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setFormError(null);
  }

  function handlePairChange(value) {
    setForm((prev) => ({
      ...prev,
      currency_pair: value,
      // The premium currency follows the pair's quote currency.
      premium_currency: value.slice(3),
    }));
    setRateTouched(false); // re-default to the new pair's market rate
    setPremiumTouched(false); // re-quote the premium for the new pair
    setFormError(null);
  }

  function handleTypeChange(value) {
    setForm((prev) => ({ ...prev, instrument_type: value }));
    setRateTouched(false); // re-default to the market rate (SPOT or FORWARD)
    setStrikeTouched(false);
    setDeliveryTouched(false); // re-derive delivery from the default expiry
    setPremiumTouched(false); // re-quote the premium when (re)entering OPTION
    setFormError(null);
  }

  function handleNumericInput(field, event) {
    const input = event.target;
    const cursor = input.selectionStart ?? input.value.length;
    const cleaned = input.value.replace(/,/g, "");
    // Reject any input that is not a valid (partial) decimal number.
    if (!/^-?\d*\.?\d*$/.test(cleaned)) {
      input.value = formatInput(form[field]); // restore the last valid value
      return;
    }
    const formatted = formatInput(cleaned);
    if (field === "rate") setRateTouched(true); // don't overwrite a manual rate
    if (field === "strike_rate") setStrikeTouched(true); // don't overwrite a manual strike
    if (field === "premium") setPremiumTouched(true); // don't overwrite a manual premium
    setForm((prev) => ({ ...prev, [field]: formatted }));
    setFormError(null);
    // Keep the caret where the user was typing after grouping commas.
    const nextCursor = cursorAfterCommas(formatted, input.value, cursor);
    requestAnimationFrame(() => {
      if (input.selectionStart != null) {
        input.setSelectionRange(nextCursor, nextCursor);
      }
    });
  }

  function handleExpiryChange(value) {
    setForm((prev) => {
      const next = { ...prev, expiry_date: value };
      // Delivery follows expiry + 2 business days unless the user has
      // manually chosen a delivery date.
      if (!deliveryTouched && value) {
        next.delivery_date = deliveryDateFor(value);
      }
      return next;
    });
    setFormError(null);
  }

  function handleDeliveryChange(value) {
    setForm((prev) => ({ ...prev, delivery_date: value }));
    setDeliveryTouched(true); // don't re-derive delivery from expiry
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
      setStrikeTouched(false);
      setDeliveryTouched(false);
      setPremiumTouched(false);
      setReview(null);
      onBooked?.(trade);
    }
  }

  const suggest = suggestedType(form);

  const isOption = form.instrument_type === "OPTION";

  // Auto-fill the option premium from the live pricing model once the option
  // details are complete, unless the user has manually edited the premium.
  // The quote is debounced so typing the notional/strike does not fire a
  // request per keystroke.
  useEffect(() => {
    if (!isOption || premiumTouched) return;
    const notional = toNumber(form.notional_1);
    const strike = toNumber(form.strike_rate);
    if (!(notional > 0) || !(strike > 0) || !form.expiry_date) return;

    let cancelled = false;
    const timer = setTimeout(async () => {
      try {
        const quote = await quoteOption({
          currency_pair: form.currency_pair,
          option_type: form.option_type,
          strike_rate: strike,
          expiry_date: form.expiry_date,
          notional_1: notional,
          vol: 0.1,
        });
        if (cancelled) return;
        setForm((prev) => ({
          ...prev,
          // total_premium is the full premium in the pair's quote currency.
          premium: formatInput(Number(quote.total_premium).toFixed(2)),
          premium_currency: form.currency_pair.slice(3),
        }));
      } catch {
        // Pricing may be unavailable (e.g. market data down); keep the premium.
      }
    }, 300);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [
    isOption,
    form.currency_pair,
    form.option_type,
    form.notional_1,
    form.strike_rate,
    form.expiry_date,
    premiumTouched,
  ]);

  if (review) {
    const details = review.instrument_details;
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
          {review.instrument_type === "OPTION" ? (
            <>
              <li>
                <span>Option</span>
                <strong>{details.option_type}</strong>
              </li>
              <li>
                <span>Strike</span>
                <strong>{formatRate(details.strike_rate)}</strong>
              </li>
              <li>
                <span>Exercise</span>
                <strong>{details.exercise_style}</strong>
              </li>
              <li>
                <span>Expiry</span>
                <strong>{details.expiry_date}</strong>
              </li>
              <li>
                <span>Delivery</span>
                <strong>{details.delivery_date}</strong>
              </li>
              <li>
                <span>Premium</span>
                <strong>
                  {formatNumber(details.premium)} {details.premium_currency}
                </strong>
              </li>
              <li>
                <span>Premium date</span>
                <strong>{details.premium_date}</strong>
              </li>
            </>
          ) : (
            <>
              <li>
                <span>Rate</span>
                <strong>{details.rate}</strong>
              </li>
              <li>
                <span>Counter leg</span>
                <strong>
                  {formatNumber(review.notional_2)} {review.currency_2}
                </strong>
              </li>
              <li>
                <span>Settlement</span>
                <strong>{details.settlement_date}</strong>
              </li>
            </>
          )}
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
              onChange={(e) => handleTypeChange(e.target.value)}
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
              type="text"
              inputMode="decimal"
              value={form.notional_1}
              onChange={(e) => handleNumericInput("notional_1", e)}
              required
            />
          </div>
          {isOption ? (
            <div className="field">
              <label className="field__label" htmlFor="option_type">
                Option Type
              </label>
              <select
                id="option_type"
                className="field__select"
                value={form.option_type}
                onChange={(e) => update("option_type", e.target.value)}
              >
                {OPTION_TYPES.map((optionType) => (
                  <option key={optionType} value={optionType}>
                    {optionType}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div className="field">
              <label className="field__label" htmlFor="rate">
                Rate
              </label>
              <input
                id="rate"
                className="field__input"
                type="text"
                inputMode="decimal"
                value={form.rate}
                onChange={(e) => handleNumericInput("rate", e)}
                required
              />
            </div>
          )}
        </div>

        {isOption ? (
          <>
            <div className="form__row">
              <div className="field">
                <label className="field__label" htmlFor="strike_rate">
                  Strike Rate
                </label>
                <input
                  id="strike_rate"
                  className="field__input"
                  type="text"
                  inputMode="decimal"
                  value={form.strike_rate}
                  onChange={(e) => handleNumericInput("strike_rate", e)}
                  required
                />
              </div>
              <div className="field">
                <label className="field__label" htmlFor="exercise_style">
                  Exercise Style
                </label>
                <select
                  id="exercise_style"
                  className="field__select"
                  value={form.exercise_style}
                  onChange={(e) => update("exercise_style", e.target.value)}
                >
                  {EXERCISE_STYLES.map((style) => (
                    <option key={style} value={style}>
                      {style}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="form__row">
              <div className="field">
                <label className="field__label" htmlFor="premium">
                  Premium
                </label>
                <input
                  id="premium"
                  className="field__input"
                  type="text"
                  inputMode="decimal"
                  value={form.premium}
                  onChange={(e) => handleNumericInput("premium", e)}
                  required
                />
                <p className="field__hint">
                  Auto-fills from live option pricing in{" "}
                  {form.currency_pair.slice(3)}; you can edit it.
                </p>
              </div>
              <div className="field">
                <label className="field__label" htmlFor="premium_currency">
                  Premium Currency
                </label>
                <select
                  id="premium_currency"
                  className="field__select"
                  value={form.premium_currency}
                  onChange={(e) => update("premium_currency", e.target.value)}
                >
                  {PREMIUM_CURRENCIES.map((currency) => (
                    <option key={currency} value={currency}>
                      {currency}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="form__row">
              <div className="field">
                <label className="field__label" htmlFor="premium_date">
                  Premium Date
                </label>
                <input
                  id="premium_date"
                  className="field__input"
                  type="date"
                  value={form.premium_date}
                  onChange={(e) => update("premium_date", e.target.value)}
                  required
                />
                <p className="field__hint">
                  Premium date is the spot date ({SPOT_DATE}).
                </p>
              </div>
              <div className="field">
                <label className="field__label" htmlFor="expiry_date">
                  Expiry Date
                </label>
                <input
                  id="expiry_date"
                  className="field__input"
                  type="date"
                  value={form.expiry_date}
                  onChange={(e) => handleExpiryChange(e.target.value)}
                  required
                />
              </div>
            </div>

            <div className="field">
              <label className="field__label" htmlFor="delivery_date">
                Delivery Date
              </label>
              <input
                id="delivery_date"
                className="field__input"
                type="date"
                value={form.delivery_date}
                onChange={(e) => handleDeliveryChange(e.target.value)}
                required
              />
              <p className="field__hint">
                Delivery is expiry + 2 business days and updates when the expiry
                changes.
              </p>
            </div>
          </>
        ) : (
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
        )}

        {formError && (
          <p className="form__result form__result--error">
            {formError}
            {suggest && (
              <button
                type="button"
                className="btn btn--ghost form__switch"
                onClick={() => handleTypeChange(suggest)}
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
