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
    expect(row.getByText("1,000,000")).toBeInTheDocument();
    expect(row.getByText("USD")).toBeInTheDocument();
    expect(row.getByText("1,085,000")).toBeInTheDocument();
    expect(row.getByText("2026-08-19")).toBeInTheDocument();
    expect(row.getByText("BANK_A")).toBeInTheDocument();
    expect(row.getByText("BOOKED")).toBeInTheDocument();
  });

  it("derives notional 2 for an OPTION as notional 1 × strike rate", () => {
    const optionTrade = {
      ...trade,
      instrument_type: "OPTION",
      notional_2: undefined,
      comment: "1M EUR call USD put at 1.085",
      instrument_details: {
        instrument_type: "OPTION",
        option_type: "CALL",
        strike_rate: 1.085,
        expiry_date: "2027-07-30",
        delivery_date: "2027-08-02",
        premium_date: "2026-08-19",
        premium: 12500,
        premium_currency: "USD",
        exercise_style: "EUROPEAN",
      },
    };
    renderBlotter({ trades: [optionTrade] });
    const row = within(screen.getByRole("row", { name: /abc-123/ }));
    expect(row.getByText("1,085,000")).toBeInTheDocument();
  });

  it("shows all trade fields in the row", () => {
    renderBlotter({ trades: [trade] });
    const row = within(screen.getByRole("row", { name: /abc-123/ }));
    expect(row.getByText("2026-08-16")).toBeInTheDocument(); // trade date
    expect(row.getByText("2026-08-19")).toBeInTheDocument(); // settlement
    expect(row.queryByText("CALL")).not.toBeInTheDocument(); // spot has no option fields
    expect(row.getAllByText("—").length).toBeGreaterThan(0); // option cols are empty
  });

  it("shows all OPTION fields in the row", () => {
    const optionTrade = {
      ...trade,
      instrument_type: "OPTION",
      notional_2: undefined,
      comment: "1M EUR call USD put at 1.085",
      instrument_details: {
        instrument_type: "OPTION",
        option_type: "CALL",
        strike_rate: 1.085,
        expiry_date: "2027-07-30",
        delivery_date: "2027-08-02",
        premium_date: "2026-08-19",
        premium: 12500,
        premium_currency: "USD",
        exercise_style: "EUROPEAN",
      },
    };
    renderBlotter({ trades: [optionTrade] });
    const row = within(screen.getByRole("row", { name: /abc-123/ }));
    expect(row.getByText("CALL")).toBeInTheDocument();
    expect(row.getByText("2027-07-30")).toBeInTheDocument(); // expiry
    expect(row.getByText("2027-08-02")).toBeInTheDocument(); // delivery
    expect(row.getByText("2026-08-19")).toBeInTheDocument(); // premium date
    expect(row.getByText("12,500")).toBeInTheDocument(); // premium
    expect(row.getAllByText("USD").length).toBeGreaterThanOrEqual(2); // currency 2 + premium ccy
    expect(row.getByText("EUROPEAN")).toBeInTheDocument(); // exercise style
    expect(row.getByText("1M EUR call USD put at 1.085")).toBeInTheDocument(); // comment
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
