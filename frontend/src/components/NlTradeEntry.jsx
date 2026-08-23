import { useEffect, useState } from "react";
import { useBookTrade } from "../hooks/useBookTrade.js";
import { useNlParse } from "../hooks/useNlParse.js";
import { fetchParseModels } from "../services/nlParse.js";

const EXAMPLES = [
  "Buy 1 million euros against dollars, spot",
  "Sell 500k GBP for USD settling 2026-11-30 at 1.27",
  "Buy a European call on EURUSD strike 1.10 expiring 2026-12-18, notional 500k",
];

const FALLBACK_MODELS = [
  { id: "rule-based", label: "Rule-based baseline", kind: "baseline" },
];

function formatNumber(value) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function ReviewRow({ label, value }) {
  return (
    <li>
      <span>{label}</span>
      <strong>{value ?? "—"}</strong>
    </li>
  );
}

export function NlTradeEntry({ onBooked }) {
  const [models, setModels] = useState([]);
  const [text, setText] = useState("");
  const [model, setModel] = useState("rule-based");
  const { result, loading, error, parse, clear } = useNlParse();
  const { submit, submitting, result: bookResult, error: bookError } = useBookTrade();

  useEffect(() => {
    let active = true;
    fetchParseModels()
      .then((list) => active && setModels(list))
      .catch(() => active && setModels(FALLBACK_MODELS));
    return () => {
      active = false;
    };
  }, []);

  async function handleParse(event) {
    event.preventDefault();
    await parse(text, model);
  }

  async function handleConfirm() {
    const trade = await submit(result.trade);
    if (trade) {
      clear();
      setText("");
      onBooked?.(trade);
    }
  }

  if (result) {
    const t = result.trade;
    const details = t.instrument_details ?? {};
    return (
      <div className="panel__body nl-entry">
        <div className="panel__header">
          <h2 className="panel__title">Review Parsed Trade</h2>
          <span className="badge badge--info">model: {result.model}</span>
        </div>
        <ul className="review">
          <ReviewRow label="Type" value={t.instrument_type} />
          <ReviewRow label="Pair" value={t.currency_pair} />
          <ReviewRow label="Direction" value={t.direction} />
          <ReviewRow
            label="Notional"
            value={`${formatNumber(t.notional_1)} ${t.currency_1}`}
          />
          <ReviewRow
            label={t.instrument_type === "OPTION" ? "Strike" : "Rate"}
            value={details.strike_rate ?? details.rate}
          />
          <ReviewRow
            label={t.instrument_type === "OPTION" ? "Expiry" : "Settlement"}
            value={details.expiry_date ?? details.settlement_date}
          />
          {t.instrument_type === "OPTION" && (
            <>
              <ReviewRow label="Option type" value={details.option_type} />
              <ReviewRow label="Exercise" value={details.exercise_style} />
              <ReviewRow
                label="Premium"
                value={`${formatNumber(details.premium ?? 0)} ${details.premium_currency ?? ""}`}
              />
            </>
          )}
          <ReviewRow label="Counterparty" value={t.counterparty} />
        </ul>
        {bookError && <p className="form__result form__result--error">{bookError}</p>}
        {bookResult && (
          <p className="form__result form__result--ok">
            Booked {bookResult.currency_pair} — {bookResult.trade_id}
          </p>
        )}
        <div className="form__actions">
          <button className="btn btn--ghost" onClick={clear} disabled={submitting}>
            Edit
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
    <div className="panel__body nl-entry">
      <div className="panel__header">
        <h2 className="panel__title">Natural Language Trade</h2>
      </div>
      <form className="form form--row" onSubmit={handleParse}>
        <div className="field nl-entry__text">
          <label className="field__label" htmlFor="nl_text">
            Instruction
          </label>
          <textarea
            id="nl_text"
            className="field__input"
            rows="2"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={EXAMPLES[0]}
            required
          />
        </div>
        <div className="field">
          <label className="field__label" htmlFor="nl_model">
            Model
          </label>
          <select
            id="nl_model"
            className="field__select"
            value={model}
            onChange={(e) => setModel(e.target.value)}
          >
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>
        </div>
        <button className="btn btn--primary" type="submit" disabled={loading || !text}>
          {loading ? "Parsing…" : "Parse & Review"}
        </button>
      </form>
      {error && <p className="form__result form__result--error">{error}</p>}
      <p className="field__hint">
        Try: “{EXAMPLES[1]}” or “{EXAMPLES[2]}”
      </p>
    </div>
  );
}
