import { useEffect, useState } from "react";
import {
  fetchSupportedPairs,
  SUPPORTED_PAIRS,
} from "../services/marketData.js";

// Shared module-level cache so every consumer fetches the live list once and
// the same array identity is reused across renders.
let cached = SUPPORTED_PAIRS;
let inflight = null;

// Returns the list of supported currency pairs. Renders immediately with the
// static fallback, then swaps to the backend-provided list once it arrives.
export function useSupportedPairs() {
  const [pairs, setPairs] = useState(cached);

  useEffect(() => {
    let active = true;
    if (!inflight) {
      inflight = fetchSupportedPairs()
        .then((list) => {
          cached = list;
          return list;
        })
        .catch(() => {
          cached = SUPPORTED_PAIRS;
          return cached;
        });
    }
    inflight.then((list) => {
      if (active) setPairs(list);
    });
    return () => {
      active = false;
    };
  }, []);

  return pairs;
}
