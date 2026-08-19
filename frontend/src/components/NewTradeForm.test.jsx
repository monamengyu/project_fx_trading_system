import { fireEvent, render, screen } from "@testing-library/react";
import { NewTradeForm } from "./NewTradeForm.jsx";
import userEvent from "@testing-library/user-event";
import { bookTrade } from "../services/trades.js";
import { addBusinessDays, toISODate } from "../utils/date.js";

vi.mock("../services/trades.js", () => ({ bookTrade: vi.fn() }));

const mockRates = {
  EURUSD: { pair: "EURUSD", rate: 1.085, as_of: "2026-08-19" },
  GBPUSD: { pair: "GBPUSD", rate: 1.27, as_of: "2026-08-19" },
  USDJPY: { pair: "USDJPY", rate: 150.12, as_of: "2026-08-19" },
};

vi.mock("../hooks/useMarketRates.js", () => ({
  useMarketRates: () => ({
    rates: mockRates,
    loading: false,
    error: null,
    refresh: vi.fn(),
  }),
}));

const FORWARD_SETTLEMENT = toISODate(addBusinessDays(new Date(), 10));

async function reviewDefault(user) {
  await user.click(screen.getByRole("button", { name: "Review Trade" }));
}

function setType(type) {
  fireEvent.change(screen.getByLabelText("Instrument Type"), {
    target: { value: type },
  });
}

function setSettlement(date) {
  fireEvent.change(screen.getByLabelText("Settlement Date"), {
    target: { value: date },
  });
}

describe("NewTradeForm", () => {
  beforeEach(() => {
    bookTrade.mockReset();
  });

  it("shows a confirmation review before booking (SPOT)", async () => {
    const user = userEvent.setup();
    render(<NewTradeForm onBooked={vi.fn()} />);

    await reviewDefault(user);

    expect(screen.getByRole("heading", { name: "Confirm Trade" })).toBeInTheDocument();
    expect(screen.getByText("EURUSD")).toBeInTheDocument();
    expect(screen.getByText(/1,085,000/)).toBeInTheDocument(); // derived counter leg
  });

  it("books on confirm and calls onBooked", async () => {
    bookTrade.mockResolvedValue({ trade_id: "1", status: "PENDING_CONFIRMATION" });
    const onBooked = vi.fn();
    const user = userEvent.setup();
    render(<NewTradeForm onBooked={onBooked} />);

    await reviewDefault(user);
    await user.click(screen.getByRole("button", { name: "Confirm & Book" }));

    expect(bookTrade).toHaveBeenCalledTimes(1);
    expect(bookTrade.mock.calls[0][0].notional_2).toBe(1085000);
    expect(bookTrade.mock.calls[0][0].instrument_type).toBe("SPOT");
    expect(onBooked).toHaveBeenCalledTimes(1);
  });

  it("goes back to the form without booking", async () => {
    const user = userEvent.setup();
    render(<NewTradeForm onBooked={vi.fn()} />);

    await reviewDefault(user);
    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByRole("heading", { name: "New Trade" })).toBeInTheDocument();
    expect(bookTrade).not.toHaveBeenCalled();
  });

  it("defaults the rate to the market rate for the selected pair", async () => {
    render(<NewTradeForm onBooked={vi.fn()} />);
    expect(screen.getByLabelText("Rate").value).toBe("1.0850");
  });

  it("updates the rate to the new pair's market rate on pair change", async () => {
    render(<NewTradeForm onBooked={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Currency Pair"), {
      target: { value: "GBPUSD" },
    });
    expect(screen.getByLabelText("Rate").value).toBe("1.2700");
  });

  it("defaults the rate to the market rate when switching to FORWARD", async () => {
    render(<NewTradeForm onBooked={vi.fn()} />);
    setType("FORWARD");
    expect(screen.getByLabelText("Rate").value).toBe("1.0850");
  });

  it("re-defaults the rate to the market rate on type switch after a manual edit", async () => {
    render(<NewTradeForm onBooked={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Rate"), {
      target: { value: "1.9999" },
    });
    expect(screen.getByLabelText("Rate").value).toBe("1.9999");

    setType("FORWARD");
    expect(screen.getByLabelText("Rate").value).toBe("1.0850");
  });

  it("keeps a manually entered rate", async () => {
    render(<NewTradeForm onBooked={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Rate"), {
      target: { value: "1.9999" },
    });
    expect(screen.getByLabelText("Rate").value).toBe("1.9999");
  });

  it("books a FORWARD trade with a later settlement date", async () => {
    bookTrade.mockResolvedValue({ trade_id: "2", status: "PENDING_CONFIRMATION" });
    const onBooked = vi.fn();
    const user = userEvent.setup();
    render(<NewTradeForm onBooked={onBooked} />);

    setType("FORWARD");
    setSettlement(FORWARD_SETTLEMENT);
    await reviewDefault(user);

    expect(screen.getByRole("heading", { name: "Confirm Trade" })).toBeInTheDocument();
    expect(screen.getByText("FORWARD")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirm & Book" }));
    const payload = bookTrade.mock.calls[0][0];
    expect(payload.instrument_type).toBe("FORWARD");
    expect(payload.instrument_details.instrument_type).toBe("FORWARD");
    expect(payload.instrument_details.settlement_date).toBe(FORWARD_SETTLEMENT);
    expect(onBooked).toHaveBeenCalledTimes(1);
  });

  it("rejects a SPOT settlement beyond the spot window and offers FORWARD", async () => {
    const user = userEvent.setup();
    render(<NewTradeForm onBooked={vi.fn()} />);

    setSettlement(FORWARD_SETTLEMENT);
    await reviewDefault(user);

    expect(screen.getByText(/use FORWARD/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Confirm Trade" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Switch to FORWARD" }));
    await reviewDefault(user);
    expect(screen.getByRole("heading", { name: "Confirm Trade" })).toBeInTheDocument();
    expect(bookTrade).not.toHaveBeenCalled();
  });

  it("rejects a settlement date on a weekend", async () => {
    const user = userEvent.setup();
    render(<NewTradeForm onBooked={vi.fn()} />);

    // a Saturday strictly after the spot value date
    const start = addBusinessDays(new Date(), 3);
    const d = new Date(start);
    while (d.getDay() !== 6) d.setDate(d.getDate() + 1);
    const saturday = toISODate(d);

    setType("FORWARD");
    setSettlement(saturday);
    await reviewDefault(user);

    expect(screen.getByText(/business day/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Confirm Trade" }),
    ).not.toBeInTheDocument();
  });

  it("rejects a SPOT settlement before today", async () => {
    const user = userEvent.setup();
    render(<NewTradeForm onBooked={vi.fn()} />);

    // a past business day (guaranteed weekday, before today)
    const past = new Date();
    past.setDate(past.getDate() - 3);
    while (past.getDay() === 0 || past.getDay() === 6) {
      past.setDate(past.getDate() - 1);
    }
    setSettlement(toISODate(past));
    await reviewDefault(user);

    expect(screen.getByText(/cannot settle before/i)).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Confirm Trade" }),
    ).not.toBeInTheDocument();
  });
});
