import { useCallback, useState } from "react";
import { parseTrade } from "../services/nlParse.js";

export function useNlParse() {
  const [result, setResult] = useState(null); // { model, draft, trade, raw }
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const parse = useCallback(async (text, model) => {
    setLoading(true);
    setError(null);
    try {
      const data = await parseTrade(text, model);
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
  }, []);

  return { result, loading, error, parse, clear };
}
