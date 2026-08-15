import { useMarketRates } from "../hooks/useMarketRates.js";
import { SUPPORTED_PAIRS } from "../services/marketData.js";

export function MarketRatesPanel() {
  const { rates, loading, error } = useMarketRates();

  return (
    <div className="panel__body">
      <h2 className="panel__title">Market Data</h2>
      {error && <p className="panel__error">{error}</p>}
      {!error && loading && Object.keys(rates).length === 0 && (
        <p className="panel__hint">Loading rates…</p>
      )}
      <ul className="rates">
        {SUPPORTED_PAIRS.map((pair) => {
          const entry = rates[pair];
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
