import { api } from "./api.js";

export async function fetchParseModels() {
  return api.get("/nl-parse/models");
}

export async function parseTrade(text, model = "rule-based") {
  return api.post("/nl-parse", { text, model });
}
