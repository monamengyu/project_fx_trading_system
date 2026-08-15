import { useCallback, useEffect, useState } from "react";
import { fetchRate, SUPPORTED_PAIRS } from "../services/marketData.js";

// Fetches the latest rate for each supported pair and keeps them in a map
// keyed by pair, refreshing on an interval.
export function useMarketRates(pairs = SUPPORTED_PAIRS, refreshMs = 60000) {
  const [rates, setRates] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const entries = await Promise.all(pairs.map((pair) => fetchRate(pair)));
      const next = {};
      entries.forEach((entry, index) => {
        next[pairs[index]] = entry;
      });
      setRates(next);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [pairs]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, refreshMs);
    return () => clearInterval(id);
  }, [refresh, refreshMs]);

  return { rates, loading, error, refresh };
}
