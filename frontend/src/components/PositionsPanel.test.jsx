import { act, render, screen, within } from "@testing-library/react";
import { PositionsPanel } from "./PositionsPanel.jsx";
import { fetchPositions } from "../services/positions.js";

vi.mock("../services/positions.js", () => ({
  fetchPositions: vi.fn(),
}));

// REST snapshot is a couple of trades stale relative to the live stream: the
// EURUSD row predates the second leg, GBPUSD has no live messages at all.
const REST_POSITIONS = [
  {
    currency_pair: "EURUSD",
    delta: 1400000,
    gamma: 0,
    vega: 0,
    theta: 0,
    mtm_value: 91000,
  },
  {
    currency_pair: "GBPUSD",
    delta: -250000,
    gamma: 0,
    vega: 0,
    theta: 0,
    mtm_value: -15000,
  },
];

function liveMessage(tradeId, pair, overrides = {}) {
  return {
    trade_id: tradeId,
    currency_pair: pair,
    mtm_value: 65000,
    greeks: { delta: 1000000, gamma: 0, vega: 0, theta: 0 },
    as_of: "2026-08-14T09:30:00Z",
    ...overrides,
  };
}

describe("PositionsPanel", () => {
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

    emit(payload) {
      this.onmessage?.({ data: payload });
    }
  }

  function emitLive(message) {
    FakeWebSocket.instances[0].emit(JSON.stringify(message));
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    FakeWebSocket.instances.length = 0;
  });

  beforeEach(() => {
    fetchPositions.mockReset();
    fetchPositions.mockResolvedValue(REST_POSITIONS);
  });

  it("renders REST positions without a live badge when no stream is received", async () => {
    render(<PositionsPanel />);

    const eurRow = within(await screen.findByRole("row", { name: /EURUSD/ }));
    expect(eurRow.getByText("1,400,000")).toBeInTheDocument();
    expect(eurRow.getByText("91,000")).toBeInTheDocument();
    expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
  });

  it("overlays per-pair aggregated live MTM and greeks and shows the LIVE badge", async () => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    render(<PositionsPanel />);
    await screen.findByRole("row", { name: /EURUSD/ });

    // Two BOOKED EURUSD legs streamed per-trade; the panel sums them per pair.
    act(() => {
      emitLive(
        liveMessage("t1", "EURUSD", { mtm_value: 65000 }),
      );
      emitLive(
        liveMessage("t2", "EURUSD", {
          mtm_value: 32500,
          greeks: { delta: 500000, gamma: 0, vega: 0, theta: 0 },
        }),
      );
    });

    const eurRow = within(screen.getByRole("row", { name: /EURUSD/ }));
    expect(eurRow.getByText("1,500,000")).toBeInTheDocument();
    expect(eurRow.getByText("97,500")).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();

    // GBPUSD has no live messages yet, so it keeps its REST values.
    const gbpRow = within(screen.getByRole("row", { name: /GBPUSD/ }));
    expect(gbpRow.getByText("-250,000")).toBeInTheDocument();
    expect(gbpRow.getByText("-15,000")).toBeInTheDocument();
  });

  it("falls back to the REST snapshot when the live stream goes stale", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      vi.stubGlobal("WebSocket", FakeWebSocket);
      render(<PositionsPanel />);
      const eurRow = within(await screen.findByRole("row", { name: /EURUSD/ }));
      expect(eurRow.getByText("1,400,000")).toBeInTheDocument();

      act(() => {
        emitLive(
          liveMessage("t1", "EURUSD", { mtm_value: 39000, greeks: { delta: 600000 } }),
        );
      });
      expect(eurRow.getByText("600,000")).toBeInTheDocument();
      expect(screen.getByText("LIVE")).toBeInTheDocument();

      act(() => {
        vi.advanceTimersByTime(16000);
      });
      expect(screen.queryByText("LIVE")).not.toBeInTheDocument();
      expect(eurRow.getByText("1,400,000")).toBeInTheDocument();
      expect(eurRow.getByText("91,000")).toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });
});
