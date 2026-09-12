import { useEffect, useRef, useState } from "react";
import { usePositions } from "../hooks/usePositions.js";
import { useTradeMtmSocket } from "../hooks/useTradeMtmSocket.js";

function formatNumber(value) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

// The /ws/positions stream pushes per-trade values roughly every 5s; treat the
// stream as down after missing several cycles and fall back to the REST snapshot.
const LIVE_STALE_MS = 15000;
const EMPTY_LIVE = { delta: 0, gamma: 0, vega: 0, theta: 0, mtm_value: 0 };

export function PositionsPanel() {
  const { positions, loading, error, refresh } = usePositions();

  // Live per-pair aggregates from /ws/positions (sums of the latest per-trade
  // MTM/greeks), overlaying the REST snapshot rows.
  const [liveByPair, setLiveByPair] = useState({});
  const [connected, setConnected] = useState(false);
  const latestByTrade = useRef({});
  const staleTimer = useRef(null);

  // Keep the position summary fresh without user interaction.
  useEffect(() => {
    const id = setInterval(refresh, 30000);
    return () => clearInterval(id);
  }, [refresh]);

  // Aggregate the latest per-trade values into per-pair sums.
  useTradeMtmSocket((message) => {
    if (!message?.trade_id || !message.currency_pair || message.mtm_value == null) {
      return;
    }
    latestByTrade.current[message.trade_id] = message;
    const totals = {};
    for (const live of Object.values(latestByTrade.current)) {
      const greeks = live.greeks ?? {};
      const agg = (totals[live.currency_pair] ??= { ...EMPTY_LIVE });
      agg.delta += greeks.delta ?? 0;
      agg.gamma += greeks.gamma ?? 0;
      agg.vega += greeks.vega ?? 0;
      agg.theta += greeks.theta ?? 0;
      agg.mtm_value += live.mtm_value;
    }
    setLiveByPair(totals);
    setConnected(true);
    clearTimeout(staleTimer.current);
    staleTimer.current = setTimeout(() => {
      // No live messages for a while: the stream is down, so fall back to the
      // REST snapshot values.
      setLiveByPair({});
      setConnected(false);
    }, LIVE_STALE_MS);
  });

  useEffect(() => () => clearTimeout(staleTimer.current), []);

  return (
    <div className="panel__body">
      <div className="panel__header">
        <h2 className="panel__title">Positions</h2>
        {connected && <span className="badge badge--success">LIVE</span>}
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
          {positions.map((position) => {
            const live = liveByPair[position.currency_pair];
            const values = live ?? position;
            return (
              <tr key={position.currency_pair}>
                <td>{position.currency_pair}</td>
                <td>{values.delta != null ? formatNumber(values.delta) : "—"}</td>
                <td>{values.gamma != null ? formatNumber(values.gamma) : "—"}</td>
                <td>{values.vega != null ? formatNumber(values.vega) : "—"}</td>
                <td>{values.theta != null ? formatNumber(values.theta) : "—"}</td>
                <td>
                  {values.mtm_value != null ? formatNumber(values.mtm_value) : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
