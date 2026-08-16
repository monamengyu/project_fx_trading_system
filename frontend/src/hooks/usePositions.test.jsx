import { renderHook, waitFor } from "@testing-library/react";
import { usePositions } from "./usePositions.js";
import { fetchPositions } from "../services/positions.js";

vi.mock("../services/positions.js", () => ({
  fetchPositions: vi.fn(),
}));

describe("usePositions", () => {
  beforeEach(() => {
    fetchPositions.mockReset();
  });

  it("loads positions on mount", async () => {
    fetchPositions.mockResolvedValue([{ currency_pair: "EURUSD", count: 2 }]);

    const { result } = renderHook(() => usePositions());

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.positions).toEqual([{ currency_pair: "EURUSD", count: 2 }]);
    expect(result.current.error).toBeNull();
  });

  it("sets an error when the request fails", async () => {
    fetchPositions.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => usePositions());

    await waitFor(() => expect(result.current.error).toBe("boom"));
    expect(result.current.positions).toEqual([]);
  });
});
