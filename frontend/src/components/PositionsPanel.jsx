import { useEffect } from "react";
import { usePositions } from "../hooks/usePositions.js";

function formatNumber(value) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

export function PositionsPanel() {
  const { positions, loading, error, refresh } = usePositions();

  // Keep the position summary fresh without user interaction.
  useEffect(() => {
    const id = setInterval(refresh, 30000);
    return () => clearInterval(id);
  }, [refresh]);

  return (
    <div className="panel__body">
      <div className="panel__header">
        <h2 className="panel__title">Positions</h2>
        <button className="btn btn--ghost" onClick={refresh} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {error && <p className="panel__error">{error}</p>}
      {!error && !loading && positions.length === 0 && (
        <p className="panel__hint">No open positions.</p>
      )}
      <table className="blotter">
        <thead>
          <tr>
            <th>Pair</th>
            <th>Delta (c1)</th>
            <th>Gamma (% c1)</th>
            <th>Vega (% c2)</th>
            <th>Theta (c2/day)</th>
            <th>MTM (USD)</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => (
            <tr key={position.currency_pair}>
              <td>{position.currency_pair}</td>
              <td>{position.delta != null ? formatNumber(position.delta) : "—"}</td>
              <td>{position.gamma != null ? formatNumber(position.gamma) : "—"}</td>
              <td>{position.vega != null ? formatNumber(position.vega) : "—"}</td>
              <td>{position.theta != null ? formatNumber(position.theta) : "—"}</td>
              <td>
                {position.mtm_value != null ? formatNumber(position.mtm_value) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
