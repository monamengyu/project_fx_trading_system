import { useState } from "react";
import { bookTrade } from "../services/trades.js";

export function useBookTrade() {
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  async function submit(payload) {
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const trade = await bookTrade(payload);
      setResult(trade);
      return trade;
    } catch (err) {
      setError(err.message);
      return null;
    } finally {
      setSubmitting(false);
    }
  }

  return { submit, submitting, result, error };
}
