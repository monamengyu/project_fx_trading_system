import { renderHook, waitFor } from "@testing-library/react";
import { useTrades } from "./useTrades.js";
import { fetchTrades } from "../services/trades.js";

vi.mock("../services/trades.js", () => ({
  fetchTrades: vi.fn(),
}));

describe("useTrades", () => {
  beforeEach(() => {
    fetchTrades.mockReset();
  });

  it("loads trades on mount", async () => {
    fetchTrades.mockResolvedValue([{ trade_id: "1", currency_pair: "EURUSD" }]);

    const { result } = renderHook(() => useTrades());

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.trades).toEqual([{ trade_id: "1", currency_pair: "EURUSD" }]);
    expect(result.current.error).toBeNull();
  });

  it("sets an error when the request fails", async () => {
    fetchTrades.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useTrades());

    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.trades).toEqual([]);
    expect(result.current.loading).toBe(false);
  });
});
