import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { TradeBlotter } from "./TradeBlotter.jsx";
import { amendTrade, cancelTrade, confirmTrade } from "../services/trades.js";

vi.mock("../services/trades.js", () => ({
  confirmTrade: vi.fn(),
  cancelTrade: vi.fn(),
  amendTrade: vi.fn(),
}));

vi.mock("./DateRangePicker.jsx", () => ({
  DateRangePicker: ({ label, onChange }) => (
    <button
      type="button"
      onClick={() => onChange({ from: "2026-08-01", to: "2026-08-15" })}
    >
      {label}
    </button>
  ),
}));

const trade = {
  trade_id: "abc-123",
  instrument_type: "SPOT",
  currency_pair: "EURUSD",
  direction: "BUY",
  currency_1: "EUR",
  notional_1: 1000000,
  currency_2: "USD",
  notional_2: 1085000,
  counterparty: "BANK_A",
  status: "BOOKED",
  trade_date: "2026-08-16",
  instrument_details: {
    instrument_type: "SPOT",
    rate: 1.085,
    settlement_date: "2026-08-19",
  },
};

function renderBlotter(props = {}) {
  const setFilters = props.setFilters ?? vi.fn();
  const utils = render(
    <TradeBlotter
      trades={[]}
      loading={false}
      error={null}
      onRefresh={() => {}}
      filters={{}}
      setFilters={setFilters}
      {...props}
    />,
  );
  return { ...utils, setFilters };
}

describe("TradeBlotter", () => {
  beforeEach(() => {
    confirmTrade.mockReset();
    cancelTrade.mockReset();
    amendTrade.mockReset();
  });

  it("shows a hint when there are no trades", () => {
    renderBlotter();
    expect(
      screen.getByText("No trades match the current filters."),
    ).toBeInTheDocument();
  });

  it("renders trade rows with the expanded columns", () => {
    renderBlotter({ trades: [trade] });
    const row = within(screen.getByRole("row", { name: /abc-123/ }));
    expect(screen.getByText("abc-123")).toBeInTheDocument();
    expect(row.getByText("SPOT")).toBeInTheDocument();
    expect(row.getByText("EURUSD")).toBeInTheDocument();
    expect(row.getByText("BUY")).toBeInTheDocument();
    expect(row.getByText("1.085")).toBeInTheDocument();
    expect(row.getByText("EUR")).toBeInTheDocument();
    expect(row.getByText("1000000")).toBeInTheDocument();
    expect(row.getByText("USD")).toBeInTheDocument();
    expect(row.getByText("1085000")).toBeInTheDocument();
    expect(row.getByText("2026-08-19")).toBeInTheDocument();
    expect(row.getByText("BANK_A")).toBeInTheDocument();
    expect(row.getByText("BOOKED")).toBeInTheDocument();
  });

  it("shows an error when the request fails", () => {
    renderBlotter({ error: "boom" });
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("confirms a pending trade from the row action", async () => {
    confirmTrade.mockResolvedValue({});
    const onRefresh = vi.fn();
    renderBlotter({
      trades: [{ ...trade, status: "PENDING_CONFIRMATION" }],
      onRefresh,
    });

    fireEvent.click(screen.getByRole("button", { name: "Confirm" }));

    await waitFor(() => expect(onRefresh).toHaveBeenCalled());
    expect(confirmTrade).toHaveBeenCalledWith("abc-123");
  });

  it("applies a status filter via setFilters", () => {
    const setFilters = vi.fn();
    renderBlotter({ setFilters });
    fireEvent.change(screen.getByLabelText("Status"), {
      target: { value: "BOOKED" },
    });
    expect(setFilters).toHaveBeenCalledWith({ status: "BOOKED" });
  });

  it("applies a trade-date range via setFilters", () => {
    const setFilters = vi.fn();
    renderBlotter({ setFilters });
    fireEvent.click(screen.getByRole("button", { name: "Trade Date" }));
    expect(setFilters).toHaveBeenCalledWith({
      trade_date: { from: "2026-08-01", to: "2026-08-15" },
    });
  });

  it("applies a settlement-date range via setFilters", () => {
    const setFilters = vi.fn();
    renderBlotter({ setFilters });
    fireEvent.click(screen.getByRole("button", { name: "Settlement Date" }));
    expect(setFilters).toHaveBeenCalledWith({
      settlement_date: { from: "2026-08-01", to: "2026-08-15" },
    });
  });

  it("resets filters with an empty object", () => {
    const setFilters = vi.fn();
    renderBlotter({ setFilters, filters: { status: "BOOKED" } });
    fireEvent.click(screen.getByRole("button", { name: "Reset" }));
    expect(setFilters).toHaveBeenCalledWith({});
  });
});
