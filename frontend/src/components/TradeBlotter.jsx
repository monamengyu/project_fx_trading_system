import { useEffect, useState } from "react";
import { StatusBadge } from "./StatusBadge.jsx";
import { DateRangePicker } from "./DateRangePicker.jsx";
import { AmendTradeDialog } from "./AmendTradeDialog.jsx";
import { useTradeMtmSocket } from "../hooks/useTradeMtmSocket.js";
import { useSupportedPairs } from "../hooks/useSupportedPairs.js";
import { cancelTrade, confirmTrade } from "../services/trades.js";

const STATUSES = ["PENDING_CONFIRMATION", "BOOKED", "CANCELLED", "MATURED"];
const TYPES = ["SPOT", "FORWARD", "OPTION"];

function clean(obj) {
  const out = {};
  for (const [key, value] of Object.entries(obj)) {
    if (value == null) continue;
    if (typeof value === "object") {
      if (value.from || value.to) out[key] = value;
    } else if (value !== "") {
      out[key] = value;
    }
  }
  return out;
}

// Notional 2 is notional 1 × strike (strike_rate for options, rate otherwise).
// SPOT/FORWARD trades store it, OPTION trades derive it at display time.
function notional2For(trade) {
  if (trade.notional_2 != null) return trade.notional_2;
  const strike =
    trade.instrument_details?.strike_rate ?? trade.instrument_details?.rate;
  if (trade.notional_1 == null || strike == null) return null;
  return Math.round(trade.notional_1 * strike * 100) / 100;
}

// Display helpers: group thousands with commas; rates keep their precision.
function formatNumber(value) {
  if (value == null) return null;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function formatRate(value) {
  if (value == null) return null;
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(value);
}

export function TradeBlotter({
  trades,
  loading,
  error,
  onRefresh,
  filters,
  setFilters,
}) {
  const PAIRS = useSupportedPairs();
  const [busyId, setBusyId] = useState(null);
  const [amending, setAmending] = useState(null); // trade being amended
  const [draft, setDraft] = useState(filters ?? {});
  // live MTM overlay from the /ws/positions stream, keyed by trade id
  const [mtmById, setMtmById] = useState({});
  const [mtmConnected, setMtmConnected] = useState(false);

  // Keep the blotter fresh without user interaction.
  useEffect(() => {
    const id = setInterval(onRefresh, 30000);
    return () => clearInterval(id);
  }, [onRefresh]);

  // Live per-trade MTM values overlay the REST snapshot.
  useTradeMtmSocket((message) => {
    if (message?.trade_id && message.mtm_value != null) {
      setMtmById((prev) => ({ ...prev, [message.trade_id]: message.mtm_value }));
      setMtmConnected(true);
    }
  });

  function handleChange(key, value) {
    const next = { ...draft, [key]: value };
    setDraft(next);
    setFilters(clean(next));
  }

  function handleDateRange(key, range) {
    const next = { ...draft, [key]: range };
    setDraft(next);
    setFilters(clean(next));
  }

  function resetFilters() {
    setDraft({});
    setFilters({});
  }

  async function handleStatus(tradeId, action) {
    setBusyId(tradeId);
    try {
      if (action === "confirm") {
        await confirmTrade(tradeId);
      } else {
        await cancelTrade(tradeId);
      }
      onRefresh();
    } catch {
      // keep current data; the user can retry
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="panel__body">
      <div className="panel__header">
        <h2 className="panel__title">Trade Blotter</h2>
        {mtmConnected && <span className="badge badge--success">LIVE</span>}
        <button className="btn btn--ghost" onClick={onRefresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      <div className="blotter__filters">
        <label className="blotter__filter">
          Status
          <select
            value={draft.status ?? ""}
            onChange={(e) => handleChange("status", e.target.value)}
          >
            <option value="">All</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="blotter__filter">
          Pair
          <select
            value={draft.currency_pair ?? ""}
            onChange={(e) => handleChange("currency_pair", e.target.value)}
          >
            <option value="">All</option>
            {PAIRS.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="blotter__filter">
          Type
          <select
            value={draft.instrument_type ?? ""}
            onChange={(e) => handleChange("instrument_type", e.target.value)}
          >
            <option value="">All</option>
            {TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
        <DateRangePicker
          label="Trade Date"
          value={draft.trade_date ?? {}}
          onChange={(range) => handleDateRange("trade_date", range)}
        />
        <DateRangePicker
          label="Settlement Date"
          value={draft.settlement_date ?? {}}
          onChange={(range) => handleDateRange("settlement_date", range)}
        />
        <button className="btn btn--ghost" onClick={resetFilters}>
          Reset
        </button>
      </div>
      {error && <p className="panel__error">{error}</p>}
      {!error && !loading && trades.length === 0 && (
        <p className="panel__hint">No trades match the current filters.</p>
      )}
      <table className="blotter">
        <thead>
          <tr>
            <th>Trade ID</th>
            <th>Type</th>
            <th>Pair</th>
            <th>Direction</th>
            <th>Trade Date</th>
            <th>Rate</th>
            <th>Option</th>
            <th>Expiry</th>
            <th>Delivery</th>
            <th>Premium Date</th>
            <th>Premium</th>
            <th>Premium Ccy</th>
            <th>Exercise</th>
            <th>Currency 1</th>
            <th>Notional 1</th>
            <th>Currency 2</th>
            <th>Notional 2</th>
            <th>Settlement</th>
            <th>Counterparty</th>
            <th>Status</th>
            <th>MTM (USD)</th>
            <th>Actions</th>
            <th>Comment</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => {
            const details = trade.instrument_details ?? {};
            return (
              <tr key={trade.trade_id}>
                <td className="blotter__id">{trade.trade_id}</td>
                <td>{trade.instrument_type}</td>
                <td>{trade.currency_pair}</td>
                <td>{trade.direction}</td>
                <td>{trade.trade_date ?? "—"}</td>
                <td>{formatRate(details.strike_rate ?? details.rate) ?? "—"}</td>
                <td>{details.option_type ?? "—"}</td>
                <td>{details.expiry_date ?? "—"}</td>
                <td>{details.delivery_date ?? "—"}</td>
                <td>{details.premium_date ?? "—"}</td>
                <td>{formatNumber(details.premium) ?? "—"}</td>
                <td>{details.premium_currency ?? "—"}</td>
                <td>{details.exercise_style ?? "—"}</td>
                <td>{trade.currency_1}</td>
                <td>{formatNumber(trade.notional_1) ?? "—"}</td>
                <td>{trade.currency_2}</td>
                <td>{formatNumber(notional2For(trade)) ?? "—"}</td>
                <td>{details.settlement_date ?? "—"}</td>
                <td>{trade.counterparty}</td>
                <td>
                  <StatusBadge status={trade.status} />
                </td>
                <td>
                  {trade.status === "BOOKED" &&
                  mtmById[trade.trade_id] != null ? (
                    <span
                      className={
                        mtmById[trade.trade_id] < 0
                          ? "blotter__mtm blotter__mtm--negative"
                          : "blotter__mtm"
                      }
                    >
                      {formatNumber(mtmById[trade.trade_id])}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="blotter__actions">
                  {trade.status === "PENDING_CONFIRMATION" && (
                    <button
                      className="btn btn--ghost"
                      disabled={busyId === trade.trade_id}
                      onClick={() => handleStatus(trade.trade_id, "confirm")}
                    >
                      Confirm
                    </button>
                  )}
                  {(trade.status === "PENDING_CONFIRMATION" ||
                    trade.status === "BOOKED") && (
                    <button
                      className="btn btn--ghost"
                      disabled={busyId === trade.trade_id}
                      onClick={() => handleStatus(trade.trade_id, "cancel")}
                    >
                      Cancel
                    </button>
                  )}
                  {trade.status === "BOOKED" && (
                    <button
                      className="btn btn--ghost"
                      disabled={busyId === trade.trade_id}
                      onClick={() => setAmending(trade)}
                    >
                      Amend
                    </button>
                  )}
                </td>
                <td>{trade.comment || "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {amending && (
        <AmendTradeDialog
          trade={amending}
          onClose={() => setAmending(null)}
          onSaved={() => {
            setAmending(null);
            onRefresh();
          }}
        />
      )}
    </div>
  );
}
