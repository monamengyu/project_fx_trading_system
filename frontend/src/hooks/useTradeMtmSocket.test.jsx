import { renderHook } from "@testing-library/react";
import { useTradeMtmSocket } from "./useTradeMtmSocket.js";

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

describe("useTradeMtmSocket", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    FakeWebSocket.instances.length = 0;
  });

  it("calls onMtm with parsed messages", () => {
    const onMtm = vi.fn();
    vi.stubGlobal("WebSocket", FakeWebSocket);

    renderHook(() => useTradeMtmSocket(onMtm));

    const socket = FakeWebSocket.instances[0];
    socket.emit(
      '{"trade_id":"abc-123","mtm_value":1250.5,"as_of":"2026-08-14T09:30:00Z"}',
    );
    expect(onMtm).toHaveBeenCalledWith({
      trade_id: "abc-123",
      mtm_value: 1250.5,
      as_of: "2026-08-14T09:30:00Z",
    });
  });

  it("reconnects after the connection closes", () => {
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeWebSocket);
    try {
      renderHook(() => useTradeMtmSocket(vi.fn()));

      expect(FakeWebSocket.instances).toHaveLength(1);
      FakeWebSocket.instances[0].close();
      vi.advanceTimersByTime(3000);
      expect(FakeWebSocket.instances).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
