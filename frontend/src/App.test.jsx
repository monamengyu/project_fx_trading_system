import { render, screen } from "@testing-library/react";
import App from "./App.jsx";

// Avoid real network calls: stub the data hooks the panels use.
vi.mock("./hooks/useTrades.js", () => ({
  useTrades: () => ({
    trades: [],
    loading: false,
    error: null,
    refresh: vi.fn(),
    filters: {},
    setFilters: vi.fn(),
  }),
}));
vi.mock("./hooks/useMarketRates.js", () => ({
  useMarketRates: () => ({ rates: {}, loading: false, error: null, refresh: vi.fn() }),
}));
vi.mock("./hooks/useSupportedPairs.js", () => ({
  useSupportedPairs: () => ["EURUSD", "GBPUSD", "USDJPY"],
}));
vi.mock("./services/nlParse.js", () => ({
  fetchParseModels: vi.fn().mockResolvedValue([]),
  parseTrade: vi.fn(),
}));

vi.mock("./hooks/usePositions.js", () => ({
  usePositions: () => ({
    positions: [],
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

describe("App", () => {
  it("renders the dashboard layout", () => {
    render(<App />);

    expect(screen.getByRole("heading", { name: "Market Data" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Trade Blotter" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "New Trade" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Positions" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Natural Language Trade" }),
    ).toBeInTheDocument();
  });
});
