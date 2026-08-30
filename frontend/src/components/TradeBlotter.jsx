import { useEffect, useState } from "react";
import { StatusBadge } from "./StatusBadge.jsx";
import { DateRangePicker } from "./DateRangePicker.jsx";
import { amendTrade, cancelTrade, confirmTrade } from "../services/trades.js";

const STATUSES = ["PENDING_CONFIRMATION", "BOOKED", "CANCELLED", "MATURED"];
const PAIRS = ["EURUSD", "GBPUSD", "USDJPY"];
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

export function TradeBlotter({
  trades,
  loading,
  error,
  onRefresh,
  filters,
  setFilters,
}) {
  const [busyId, setBusyId] = useState(null);
  const [draft, setDraft] = useState(filters ?? {});

  // Keep the blotter fresh without user interaction.
  useEffect(() => {
    const id = setInterval(onRefresh, 30000);
    return () => clearInterval(id);
  }, [onRefresh]);

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
      } else if (action === "cancel") {
        await cancelTrade(tradeId);
      } else {
        await amendTrade(tradeId);
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
            <th>Rate</th>
            <th>Currency 1</th>
            <th>Notional 1</th>
            <th>Currency 2</th>
            <th>Notional 2</th>
            <th>Settlement</th>
            <th>Counterparty</th>
            <th>Status</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={trade.trade_id}>
              <td className="blotter__id">{trade.trade_id}</td>
              <td>{trade.instrument_type}</td>
              <td>{trade.currency_pair}</td>
              <td>{trade.direction}</td>
              <td>
                {trade.instrument_details?.strike_rate ??
                  trade.instrument_details?.rate ??
                  "—"}
              </td>
              <td>{trade.currency_1}</td>
              <td>{trade.notional_1}</td>
              <td>{trade.currency_2}</td>
              <td>{trade.notional_2 ?? "—"}</td>
              <td>
                {trade.instrument_details?.expiry_date ??
                  trade.instrument_details?.settlement_date ??
                  "—"}
              </td>
              <td>{trade.counterparty}</td>
              <td>
                <StatusBadge status={trade.status} />
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
                    onClick={() => handleStatus(trade.trade_id, "amend")}
                  >
                    Amend
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
