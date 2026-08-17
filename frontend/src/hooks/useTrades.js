import { useCallback, useEffect, useState } from "react";
import { fetchTrades } from "../services/trades.js";

export function useTrades() {
  const [trades, setTrades] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({});

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchTrades(filters);
      setTrades(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  return { trades, loading, error, refresh, filters, setFilters };
}
