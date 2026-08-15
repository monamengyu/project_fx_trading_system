import { useState } from "react";
import { useBookTrade } from "../hooks/useBookTrade.js";

const PAIRS = ["EURUSD", "GBPUSD", "USDJPY"];
const DIRECTIONS = ["BUY", "SELL"];
const COUNTERPARTIES = ["BANK_A", "BANK_B", "BANK_C"];

const EMPTY_FORM = {
  currency_pair: "EURUSD",
  direction: "BUY",
  notional_1: "1000000",
  counterparty: "BANK_A",
  rate: "1.0850",
  settlement_date: "",
};

export function NewTradeForm({ onBooked }) {
  const [form, setForm] = useState(EMPTY_FORM);
  const { submit, submitting, result, error } = useBookTrade();

  function update(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(event) {
    event.preventDefault();
    const trade = await submit({
      instrument_type: "SPOT",
      currency_pair: form.currency_pair,
      direction: form.direction,
      currency_1: form.currency_pair.slice(0, 3),
      notional_1: Number(form.notional_1),
      currency_2: form.currency_pair.slice(3),
      counterparty: form.counterparty,
      comment: "",
      instrument_details: {
        instrument_type: "SPOT",
        rate: Number(form.rate),
        settlement_date: form.settlement_date,
      },
    });
    if (trade) {
      setForm(EMPTY_FORM);
      onBooked?.(trade);
    }
  }

  return (
    <div className="panel__body">
      <h2 className="panel__title">New Trade</h2>
      <form className="form" onSubmit={handleSubmit}>
        <div className="form__row">
          <div className="field">
            <label className="field__label" htmlFor="currency_pair">
              Currency Pair
            </label>
            <select
              id="currency_pair"
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
          </div>
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
        </div>

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

        <div className="form__row">
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
              onChange={(e) => update("rate", e.target.value)}
              required
            />
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
          </div>
        </div>

        {error && <p className="form__result form__result--error">{error}</p>}
        {result && (
          <p className="form__result form__result--ok">
            Booked {result.currency_pair} {result.direction} ({result.status}) —
            {result.trade_id}
          </p>
        )}

        <button className="btn btn--primary" type="submit" disabled={submitting}>
          {submitting ? "Booking…" : "Book Trade"}
        </button>
      </form>
    </div>
  );
}
