import { api } from "./api.js";

// Pairs exposed by the backend's CurrencyPair enum.
export const SUPPORTED_PAIRS = ["EURUSD", "GBPUSD", "USDJPY"];

export async function fetchRate(pair) {
  return api.get(`/market-data/rates?pair=${encodeURIComponent(pair)}`);
}
