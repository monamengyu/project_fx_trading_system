import { api } from "./api.js";

export async function fetchTrades(filters = {}) {
  const params = new URLSearchParams();
  const add = (key, value) => {
    if (value !== "" && value != null) params.set(key, value);
  };
  Object.entries(filters).forEach(([key, value]) => {
    if (value && typeof value === "object" && !Array.isArray(value)) {
      add(`${key}_from`, value.from);
      add(`${key}_to`, value.to);
    } else {
      add(key, value);
    }
  });
  const qs = params.toString();
  return api.get(qs ? `/trades?${qs}` : "/trades");
}

export async function bookTrade(payload) {
  return api.post("/trades", payload);
}

export async function confirmTrade(tradeId, comment) {
  return api.post(`/trades/${tradeId}/confirm`, { comment });
}

export async function cancelTrade(tradeId, comment) {
  return api.post(`/trades/${tradeId}/cancel`, { comment });
}

export async function amendTrade(tradeId, comment) {
  return api.post(`/trades/${tradeId}/amend`, { comment });
}
