import { api } from "./api.js";

// Pairs exposed by the backend's CurrencyPair enum, kept in sync with
// GET /market-data/pairs. Used as the default / offline fallback until the
// live list arrives from the backend.
export const SUPPORTED_PAIRS = [
  "EURUSD",
  "GBPUSD",
  "USDJPY",
  "USDCHF",
  "USDCAD",
  "AUDUSD",
  "NZDUSD",
  "USDCNH",
  "USDSEK",
  "USDNOK",
  "USDHKD",
  "USDSGD",
  "USDMXN",
  "USDZAR",
  "USDTRY",
];

export async function fetchSupportedPairs() {
  const data = await api.get("/market-data/pairs");
  return Array.isArray(data.pairs) ? data.pairs : SUPPORTED_PAIRS;
}

export async function fetchRate(pair) {
  return api.get(`/market-data/rates?pair=${encodeURIComponent(pair)}`);
}
