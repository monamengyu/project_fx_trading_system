import { api } from "./api.js";

export async function fetchPositions() {
  return api.get("/positions");
}
