import { useRef, useState } from "react";
import { useSupportedPairs } from "../hooks/useSupportedPairs.js";
import { amendTrade } from "../services/trades.js";
import { isBusinessDay } from "../utils/date.js";

const DIRECTIONS = ["BUY", "SELL"];
const COUNTERPARTIES = ["BANK_A", "BANK_B", "BANK_C"];
const OPTION_TYPES = ["CALL", "PUT"];
const EXERCISE_STYLES = ["EUROPEAN", "AMERICAN"];
const PREMIUM_CURRENCIES = ["USD", "EUR", "GBP", "JPY"];

// Converts a form value to a number, tolerating grouping commas (NaN-safe).
function toNumber(value) {
  if (value == null || value === "") return NaN;
  return Number(String(value).replace(/,/g, ""));
}

// Converts a stored number to a plain (un-grouped) editable string.
function toText(value) {
  if (value == null) return "";
  return String(value);
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

// Rounds to two decimal places, matching how notional amounts are stored.
function round2(value) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

// OPTION trades don't persist notional 2, so derive it as notional 1 × strike.
function derivedNotionalTwo(trade) {
  const n1 = Number(trade.notional_1);
  const details = trade.instrument_details ?? {};
  const rate =
    trade.instrument_type === "OPTION"
      ? Number(details.strike_rate)
      : Number(details.rate);
  if (!Number.isFinite(n1) || !Number.isFinite(rate) || rate <= 0) return null;
  return round2(n1 * rate);
}

function initialForm(trade) {
  const details = trade.instrument_details ?? {};
  const storedNotionalTwo =
    trade.instrument_type !== "OPTION" && trade.notional_2 != null
      ? trade.notional_2
      : derivedNotionalTwo(trade);
  const common = {
    currency_pair: trade.currency_pair,
    direction: trade.direction,
    counterparty: trade.counterparty,
    notional_1: formatInput(toText(trade.notional_1)),
    notional_2: formatInput(toText(storedNotionalTwo)),
    comment: trade.comment ?? "",
  };
  if (trade.instrument_type === "OPTION") {
    return {
      ...common,
      option_type: details.option_type ?? "CALL",
      strike_rate: formatInput(toText(details.strike_rate)),
      premium_date: details.premium_date ?? "",
      expiry_date: details.expiry_date ?? "",
      delivery_date: details.delivery_date ?? "",
      premium: formatInput(toText(details.premium)),
      premium_currency: details.premium_currency ?? "USD",
      exercise_style: details.exercise_style ?? "EUROPEAN",
    };
  }
  return {
    ...common,
    rate: formatInput(toText(details.rate)),
    settlement_date: details.settlement_date ?? "",
  };
}

function buildPayload(form, trade) {
  const payload = {
    currency_pair: form.currency_pair,
    direction: form.direction,
    counterparty: form.counterparty,
    notional_1: toNumber(form.notional_1),
    comment: form.comment,
  };
  if (trade.instrument_type !== "OPTION") {
    const notionalTwo = toNumber(form.notional_2);
    if (Number.isFinite(notionalTwo) && notionalTwo > 0) {
      payload.notional_2 = notionalTwo;
    }
  }
  if (trade.instrument_type === "OPTION") {
    payload.instrument_details = {
      instrument_type: "OPTION",
      option_type: form.option_type,
      strike_rate: toNumber(form.strike_rate),
      premium_date: form.premium_date,
      expiry_date: form.expiry_date,
      delivery_date: form.delivery_date,
      premium: toNumber(form.premium),
      premium_currency: form.premium_currency,
      exercise_style: form.exercise_style,
    };
  } else {
    payload.instrument_details = {
      instrument_type: trade.instrument_type,
      rate: toNumber(form.rate),
      settlement_date: form.settlement_date,
    };
  }
  return payload;
}

function validate(form, trade) {
  if (!(toNumber(form.notional_1) > 0)) {
    return "Notional 1 must be a positive number.";
  }
  if (trade.instrument_type === "OPTION") {
    if (!form.option_type) return "Option type (CALL/PUT) is required.";
    if (!(toNumber(form.strike_rate) > 0)) {
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
    if (Number.isNaN(toNumber(form.premium)) || toNumber(form.premium) < 0) {
      return "Premium is required and cannot be negative.";
    }
    return null;
  }
  if (!(toNumber(form.rate) > 0)) return "Rate is required and must be positive.";
  if (!form.settlement_date) return "Settlement date is required.";
  if (!isBusinessDay(new Date(`${form.settlement_date}T00:00:00`))) {
    return "Settlement date must be a business day (Mon-Fri).";
  }
  return null;
}

function Field({ label, children }) {
  return (
    <label className="field">
      <span className="field__label">{label}</span>
      {children}
    </label>
  );
}

export function AmendTradeDialog({ trade, onClose, onSaved }) {
  const PAIRS = useSupportedPairs();
  const [form, setForm] = useState(() => initialForm(trade));
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);

  // Records which notional the user last edited directly. When the rate/strike
  // changes, that notional is kept fixed and the other is re-derived from it.
  const driverRef = useRef("notional_1");

  const isOption = trade.instrument_type === "OPTION";
  const dirty = Object.keys(form).some((key) => form[key] !== initialForm(trade)[key]);

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
    setError(null);
  }

  function handleNumericInput(field, event) {
    const input = event.target;
    const cursor = input.selectionStart ?? input.value.length;
    const cleaned = input.value.replace(/,/g, "");
    // Reject any input that is not a valid (partial) decimal number.
    if (!/^-?\d*\.?\d*$/.test(cleaned)) {
      input.value = form[field]; // restore the last valid value
      return;
    }
    const formatted = formatInput(cleaned);
    const next = { ...form, [field]: formatted };
    const rate = toNumber(isOption ? next.strike_rate : next.rate);
    const edited = toNumber(formatted);
    if (field === "notional_1") {
      // Keep the edited Notional 1 and derive Notional 2 = Notional 1 × rate.
      driverRef.current = "notional_1";
      if (edited > 0 && rate > 0) {
        next.notional_2 = formatInput(toText(round2(edited * rate)));
      }
    } else if (field === "notional_2") {
      // Keep the edited Notional 2 and derive Notional 1 = Notional 2 ÷ rate.
      driverRef.current = "notional_2";
      if (edited > 0 && rate > 0) {
        next.notional_1 = formatInput(toText(round2(edited / rate)));
      }
    } else if (field === "rate" || field === "strike_rate") {
      // Re-derive the non-driver notional from the new rate/strike.
      const n1 = toNumber(next.notional_1);
      const n2 = toNumber(next.notional_2);
      if (rate > 0 && n1 > 0 && n2 > 0) {
        if (driverRef.current === "notional_1") {
          next.notional_2 = formatInput(toText(round2(n1 * rate)));
        } else {
          next.notional_1 = formatInput(toText(round2(n2 / rate)));
        }
      }
    }
    setForm(next);
    setError(null);
    // Keep the caret where the user was typing after grouping commas.
    const nextCursor = cursorAfterCommas(formatted, input.value, cursor);
    requestAnimationFrame(() => {
      if (input.selectionStart != null) {
        input.setSelectionRange(nextCursor, nextCursor);
      }
    });
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const problem = validate(form, trade);
    if (problem) {
      setError(problem);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await amendTrade(trade.trade_id, buildPayload(form, trade));
      onSaved?.();
    } catch (err) {
      setError(err.message);
      setSaving(false);
    }
  }

  return (
    <div className="modal__backdrop" role="presentation">
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="amend-trade-title"
      >
        <form onSubmit={handleSubmit}>
          <div className="modal__header">
            <h2 id="amend-trade-title" className="modal__title">
              Amend Trade
            </h2>
            <span className="modal__subtitle">
              {trade.instrument_type} · {trade.currency_pair} · {trade.status}
            </span>
          </div>

          <div className="modal__body">
            <div className="form__row">
              <Field label="Currency Pair">
                <select
                  className="field__select"
                  value={form.currency_pair}
                  onChange={(e) => update("currency_pair", e.target.value)}
                >
                  {PAIRS.map((pair) => (
                    <option key={pair} value={pair}>
                      {pair}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Direction">
                <select
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
              </Field>
            </div>

            <Field label="Counterparty">
              <select
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
            </Field>

            <div className="form__row">
              <Field label="Notional 1">
                <input
                  className="field__input"
                  inputMode="decimal"
                  value={form.notional_1}
                  onChange={(e) => handleNumericInput("notional_1", e)}
                />
              </Field>
              <Field label="Notional 2">
                <input
                  className="field__input"
                  inputMode="decimal"
                  value={form.notional_2}
                  onChange={(e) => handleNumericInput("notional_2", e)}
                />
              </Field>
            </div>

            {isOption ? (
              <>
                <div className="form__row">
                  <Field label="Option Type">
                    <select
                      className="field__select"
                      value={form.option_type}
                      onChange={(e) => update("option_type", e.target.value)}
                    >
                      {OPTION_TYPES.map((type) => (
                        <option key={type} value={type}>
                          {type}
                        </option>
                      ))}
                    </select>
                  </Field>
                  <Field label="Strike Rate">
                    <input
                      className="field__input"
                      inputMode="decimal"
                      value={form.strike_rate}
                      onChange={(e) => handleNumericInput("strike_rate", e)}
                    />
                  </Field>
                </div>
                <div className="form__row">
                  <Field label="Premium Date">
                    <input
                      type="date"
                      className="field__input"
                      value={form.premium_date}
                      onChange={(e) => update("premium_date", e.target.value)}
                    />
                  </Field>
                  <Field label="Expiry Date">
                    <input
                      type="date"
                      className="field__input"
                      value={form.expiry_date}
                      onChange={(e) => update("expiry_date", e.target.value)}
                    />
                  </Field>
                </div>
                <div className="form__row">
                  <Field label="Delivery Date">
                    <input
                      type="date"
                      className="field__input"
                      value={form.delivery_date}
                      onChange={(e) => update("delivery_date", e.target.value)}
                    />
                  </Field>
                  <Field label="Premium">
                    <input
                      className="field__input"
                      inputMode="decimal"
                      value={form.premium}
                      onChange={(e) => handleNumericInput("premium", e)}
                    />
                  </Field>
                </div>
                <div className="form__row">
                  <Field label="Premium Currency">
                    <select
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
                  </Field>
                  <Field label="Exercise Style">
                    <select
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
                  </Field>
                </div>
              </>
            ) : (
              <div className="form__row">
                <Field label="Rate">
                  <input
                    className="field__input"
                    inputMode="decimal"
                    value={form.rate}
                    onChange={(e) => handleNumericInput("rate", e)}
                  />
                </Field>
                <Field label="Settlement Date">
                  <input
                    type="date"
                    className="field__input"
                    value={form.settlement_date}
                    onChange={(e) => update("settlement_date", e.target.value)}
                  />
                </Field>
              </div>
            )}

            <Field label="Comment">
              <textarea
                className="field__input"
                rows="2"
                value={form.comment}
                onChange={(e) => update("comment", e.target.value)}
              />
            </Field>

            {error && <p className="form__result form__result--error">{error}</p>}
          </div>

          <div className="modal__footer">
            <button
              type="button"
              className="btn btn--ghost"
              onClick={onClose}
              disabled={saving}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn--primary"
              disabled={!dirty || saving}
            >
              {saving ? "Saving…" : "Save Changes"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
