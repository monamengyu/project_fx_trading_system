import { act, renderHook } from "@testing-library/react";
import { useBookTrade } from "./useBookTrade.js";
import { bookTrade } from "../services/trades.js";

vi.mock("../services/trades.js", () => ({
  bookTrade: vi.fn(),
}));

describe("useBookTrade", () => {
  beforeEach(() => {
    bookTrade.mockReset();
  });

  it("returns the booked trade on success", async () => {
    bookTrade.mockResolvedValue({
      trade_id: "1",
      status: "PENDING_CONFIRMATION",
    });

    const { result } = renderHook(() => useBookTrade());
    let returned;
    await act(async () => {
      returned = await result.current.submit({ currency_pair: "EURUSD" });
    });

    expect(returned).toEqual({
      trade_id: "1",
      status: "PENDING_CONFIRMATION",
    });
    expect(result.current.result).toEqual({
      trade_id: "1",
      status: "PENDING_CONFIRMATION",
    });
    expect(result.current.error).toBeNull();
    expect(result.current.submitting).toBe(false);
  });

  it("returns null and sets an error on failure", async () => {
    bookTrade.mockRejectedValue(new Error("upstream down"));

    const { result } = renderHook(() => useBookTrade());
    let returned;
    await act(async () => {
      returned = await result.current.submit({});
    });

    expect(returned).toBeNull();
    expect(result.current.error).toBe("upstream down");
    expect(result.current.result).toBeNull();
    expect(result.current.submitting).toBe(false);
  });
});
