import { useEffect, useRef } from "react";
import { API_URL } from "../services/api.js";

const WS_URL = `${API_URL.replace(/^http/, "ws")}/ws/market-data`;

// Subscribes to live rate pushes from the backend WebSocket. `onRate` is
// called with each `{ pair, rate, as_of }` message. Reconnects automatically.
export function useMarketRatesSocket(onRate) {
  const onRateRef = useRef(onRate);
  onRateRef.current = onRate;

  useEffect(() => {
    if (typeof WebSocket === "undefined") {
      return undefined; // not a browser environment (e.g. unit tests)
    }

    let stopped = false;
    let socket = null;
    let reconnectTimer = null;

    const connect = () => {
      socket = new WebSocket(WS_URL);
      socket.onmessage = (event) => {
        try {
          onRateRef.current(JSON.parse(event.data));
        } catch {
          // ignore malformed frames
        }
      };
      socket.onclose = () => {
        if (!stopped) {
          reconnectTimer = setTimeout(connect, 3000);
        }
      };
    };

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
      }
      socket?.close();
    };
  }, []);
}
