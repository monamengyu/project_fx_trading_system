import { useState } from "react";
import { useMarketRates } from "../hooks/useMarketRates.js";
import { useMarketRatesSocket } from "../hooks/useMarketRatesSocket.js";
import { useSupportedPairs } from "../hooks/useSupportedPairs.js";

export function MarketRatesPanel() {
  const pairs = useSupportedPairs();
  const { rates, loading, error } = useMarketRates(pairs);
  const [liveRates, setLiveRates] = useState({});
  const [liveConnected, setLiveConnected] = useState(false);

  // live WebSocket updates overlay the REST snapshot
  useMarketRatesSocket((message) => {
    setLiveRates((prev) => ({ ...prev, [message.pair]: message }));
    setLiveConnected(true);
  });

  const displayRates = { ...rates, ...liveRates };

  return (
    <div className="panel__body">
      <div className="panel__header">
        <h2 className="panel__title">Market Data</h2>
        {liveConnected && <span className="badge badge--success">LIVE</span>}
      </div>
      {error && <p className="panel__error">{error}</p>}
      {!error && loading && Object.keys(displayRates).length === 0 && (
        <p className="panel__hint">Loading rates…</p>
      )}
      <ul className="rates">
        {pairs.map((pair) => {
          const entry = displayRates[pair];
          return (
            <li key={pair} className="rate">
              <span className="rate__pair">{pair}</span>
              <span className="rate__value">
                {entry ? Number(entry.rate).toFixed(4) : "—"}
              </span>
              <span className="rate__date">{entry?.as_of ?? ""}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
