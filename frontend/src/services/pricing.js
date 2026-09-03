import { api } from "./api.js";

// Live option quote (per-unit + total premium in the pair's quote currency).
export async function quoteOption(payload) {
  return api.post("/pricing/options", payload);
}
