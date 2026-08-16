import { renderHook } from "@testing-library/react";
import { useMarketRatesSocket } from "./useMarketRatesSocket.js";

class FakeWebSocket {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.onmessage = null;
    this.onclose = null;
    FakeWebSocket.instances.push(this);
  }

  close() {
    this.onclose?.();
  }

  emit(data) {
    this.onmessage?.({ data });
  }
}

describe("useMarketRatesSocket", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    FakeWebSocket.instances.length = 0;
  });

  it("calls onRate with parsed messages", () => {
    const onRate = vi.fn();
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useMarketRatesSocket(onRate));

    const socket = FakeWebSocket.instances[0];
    socket.emit('{"pair":"EURUSD","rate":1.1567,"as_of":"2026-08-14"}');
    expect(onRate).toHaveBeenCalledWith({
      pair: "EURUSD",
      rate: 1.1567,
      as_of: "2026-08-14",
    });
  });

  it("reconnects after the connection closes", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);
    try {
      renderHook(() => useMarketRatesSocket(vi.fn()));

      expect(FakeWebSocket.instances).toHaveLength(1);
      FakeWebSocket.instances[0].close();
      vi.advanceTimersByTime(3000);
      expect(FakeWebSocket.instances).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
