import { api } from "./api.js";

export async function fetchTrades() {
  return api.get("/trades");
}

export async function bookTrade(payload) {
  return api.post("/trades", payload);
}
