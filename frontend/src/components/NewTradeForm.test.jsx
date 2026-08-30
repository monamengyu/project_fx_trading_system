import { fireEvent, render, screen } from "@testing-library/react";
import { NewTradeForm } from "./NewTradeForm.jsx";
import userEvent from "@testing-library/user-event";
import { bookTrade } from "../services/trades.js";
import { addBusinessDays, toISODate, todayISO } from "../utils/date.js";

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

  describe("OPTION trades", () => {
    // Matches the component's anchor: todayISO() rolls to the next business day.
    const defaultExpiry = toISODate(
      addBusinessDays(new Date(`${todayISO()}T00:00:00`), 21),
    );
    const defaultDelivery = toISODate(
      addBusinessDays(new Date(`${defaultExpiry}T00:00:00`), 2),
    );

    function setOptionType(value) {
      fireEvent.change(screen.getByLabelText("Option Type"), {
        target: { value },
      });
    }

    function setExpiry(value) {
      fireEvent.change(screen.getByLabelText("Expiry Date"), {
        target: { value },
      });
    }

    function setDelivery(value) {
      fireEvent.change(screen.getByLabelText("Delivery Date"), {
        target: { value },
      });
    }

    it("shows a confirmation review with option details", async () => {
      const user = userEvent.setup();
      render(<NewTradeForm onBooked={vi.fn()} />);

      setType("OPTION");
      setOptionType("PUT");
      await reviewDefault(user);

      expect(screen.getByRole("heading", { name: "Confirm Trade" })).toBeInTheDocument();
      expect(screen.getByText("OPTION")).toBeInTheDocument();
      expect(screen.getByText("PUT")).toBeInTheDocument();
      expect(screen.getByText(/1,000,000/)).toBeInTheDocument(); // notional
      expect(screen.getByText(defaultExpiry)).toBeInTheDocument();
      expect(screen.getByText(defaultDelivery)).toBeInTheDocument();
      expect(screen.getByText("EUROPEAN")).toBeInTheDocument();
    });

    it("defaults the strike rate to the market rate when switching to OPTION", () => {
      render(<NewTradeForm onBooked={vi.fn()} />);
      setType("OPTION");
      expect(screen.getByLabelText("Strike Rate").value).toBe("1.0850");
    });

    it("defaults the delivery date to expiry + 2 business days", () => {
      render(<NewTradeForm onBooked={vi.fn()} />);
      setType("OPTION");
      expect(screen.getByLabelText("Expiry Date").value).toBe(defaultExpiry);
      expect(screen.getByLabelText("Delivery Date").value).toBe(defaultDelivery);
    });

    it("defaults the premium date to the spot date (today + 2 business days)", () => {
      render(<NewTradeForm onBooked={vi.fn()} />);
      setType("OPTION");
      const expectedSpot = toISODate(
        addBusinessDays(new Date(`${todayISO()}T00:00:00`), 2),
      );
      expect(screen.getByLabelText("Premium Date").value).toBe(expectedSpot);
    });

    it("updates the delivery date when the expiry date changes", () => {
      render(<NewTradeForm onBooked={vi.fn()} />);
      setType("OPTION");
      const newExpiry = toISODate(
        addBusinessDays(new Date(`${todayISO()}T00:00:00`), 30),
      );
      setExpiry(newExpiry);
      expect(screen.getByLabelText("Expiry Date").value).toBe(newExpiry);
      expect(screen.getByLabelText("Delivery Date").value).toBe(
        toISODate(addBusinessDays(new Date(`${newExpiry}T00:00:00`), 2)),
      );
    });

    it("keeps a manually chosen delivery date when the expiry changes", () => {
      render(<NewTradeForm onBooked={vi.fn()} />);
      setType("OPTION");
      const manualDelivery = toISODate(
        addBusinessDays(new Date(`${todayISO()}T00:00:00`), 25),
      );
      setDelivery(manualDelivery);
      const newExpiry = toISODate(
        addBusinessDays(new Date(`${todayISO()}T00:00:00`), 30),
      );
      setExpiry(newExpiry);
      expect(screen.getByLabelText("Delivery Date").value).toBe(manualDelivery);
    });

    it("books an OPTION trade with option instrument details and no counter leg", async () => {
      bookTrade.mockResolvedValue({ trade_id: "3", status: "PENDING_CONFIRMATION" });
      const onBooked = vi.fn();
      const user = userEvent.setup();
      render(<NewTradeForm onBooked={onBooked} />);

      setType("OPTION");
      setOptionType("CALL");
      await reviewDefault(user);
      await user.click(screen.getByRole("button", { name: "Confirm & Book" }));

      const payload = bookTrade.mock.calls[0][0];
      expect(payload.instrument_type).toBe("OPTION");
      expect(payload.notional_2).toBeUndefined();
      expect(payload.instrument_details).toEqual({
        instrument_type: "OPTION",
        option_type: "CALL",
        strike_rate: 1.085,
        premium_date: toISODate(
          addBusinessDays(new Date(`${todayISO()}T00:00:00`), 2),
        ),
        expiry_date: defaultExpiry,
        delivery_date: defaultDelivery,
        premium: 0,
        premium_currency: "USD",
        exercise_style: "EUROPEAN",
      });
      expect(onBooked).toHaveBeenCalledTimes(1);
    });

    it("rejects an option with an expiry before today", async () => {
      const user = userEvent.setup();
      render(<NewTradeForm onBooked={vi.fn()} />);

      setType("OPTION");
      const past = new Date();
      past.setDate(past.getDate() - 3);
      while (past.getDay() === 0 || past.getDay() === 6) {
        past.setDate(past.getDate() - 1);
      }
      setExpiry(toISODate(past));
      setDelivery(toISODate(past));
      await reviewDefault(user);

      expect(screen.getByText(/expiry date cannot be before/i)).toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: "Confirm Trade" }),
      ).not.toBeInTheDocument();
    });

    it("rejects a delivery date before the expiry date", async () => {
      const user = userEvent.setup();
      render(<NewTradeForm onBooked={vi.fn()} />);

      setType("OPTION");
      const earlier = toISODate(addBusinessDays(new Date(), 5));
      setExpiry(earlier);
      setDelivery(toISODate(addBusinessDays(new Date(), 3)));
      await reviewDefault(user);

      expect(
        screen.getByText(/delivery date cannot be before/i),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: "Confirm Trade" }),
      ).not.toBeInTheDocument();
    });

    it("rejects a delivery date on a weekend", async () => {
      const user = userEvent.setup();
      render(<NewTradeForm onBooked={vi.fn()} />);

      setType("OPTION");
      const start = addBusinessDays(new Date(), 4);
      const d = new Date(start);
      while (d.getDay() !== 6) d.setDate(d.getDate() + 1);
      const saturday = toISODate(d);
      setExpiry(toISODate(addBusinessDays(new Date(), 10)));
      setDelivery(saturday);
      await reviewDefault(user);

      expect(screen.getByText(/delivery date must be a business day/i)).toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: "Confirm Trade" }),
      ).not.toBeInTheDocument();
    });
  });
});
