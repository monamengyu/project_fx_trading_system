import { useEffect } from "react";
import { StatusBadge } from "./StatusBadge.jsx";

export function TradeBlotter({ trades, loading, error, onRefresh }) {
  // Keep the blotter fresh without user interaction.
  useEffect(() => {
    const id = setInterval(onRefresh, 30000);
    return () => clearInterval(id);
  }, [onRefresh]);

  return (
    <div className="panel__body">
      <div className="panel__header">
        <h2 className="panel__title">Trade Blotter</h2>
        <button className="btn btn--ghost" onClick={onRefresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {error && <p className="panel__error">{error}</p>}
      {!error && !loading && trades.length === 0 && (
        <p className="panel__hint">No trades booked yet.</p>
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
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr key={trade.trade_id}>
              <td className="blotter__id">{trade.trade_id}</td>
              <td>{trade.instrument_type}</td>
              <td>{trade.currency_pair}</td>
              <td>{trade.direction}</td>
              <td>{trade.instrument_details?.rate ?? "—"}</td>
              <td>{trade.currency_1}</td>
              <td>{trade.notional_1}</td>
              <td>{trade.currency_2}</td>
              <td>{trade.notional_2 ?? "—"}</td>
              <td>{trade.instrument_details?.settlement_date ?? "—"}</td>
              <td>{trade.counterparty}</td>
              <td>
                <StatusBadge status={trade.status} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
