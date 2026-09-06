import { useCallback, useState } from "react";
import { parseTrade } from "../services/nlParse.js";

export function useNlParse() {
  const [result, setResult] = useState(null); // { model, draft, trade, raw, usage }
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [elapsedMs, setElapsedMs] = useState(null);

  const parse = useCallback(async (text, model) => {
    setLoading(true);
    setError(null);
    setElapsedMs(null);
    const startedAt = performance.now();
    try {
      const data = await parseTrade(text, model);
      setElapsedMs(performance.now() - startedAt);
      setResult(data);
      return data;
    } catch (err) {
      setError(err.message);
      setResult(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  const clear = useCallback(() => {
    setResult(null);
    setError(null);
    setElapsedMs(null);
  }, []);

  return { result, loading, error, elapsedMs, parse, clear };
}
