import { api } from "./api.js";

export async function fetchTrades() {
  return api.get("/trades");
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
