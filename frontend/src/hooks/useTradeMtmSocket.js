import { useEffect, useRef } from "react";
import { API_URL } from "../services/api.js";

const WS_URL = `${API_URL.replace(/^http/, "ws")}/ws/positions`;

// Subscribes to live per-trade mark-to-market pushes from the backend
// WebSocket. `onMtm` is called with each `{ trade_id, mtm_value, as_of }`
// message. Reconnects automatically.
export function useTradeMtmSocket(onMtm) {
  const onMtmRef = useRef(onMtm);
  onMtmRef.current = onMtm;

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
          onMtmRef.current(JSON.parse(event.data));
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
