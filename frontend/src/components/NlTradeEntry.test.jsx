import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NlTradeEntry } from "./NlTradeEntry.jsx";
import { fetchParseModels, parseTrade } from "../services/nlParse.js";
import { bookTrade } from "../services/trades.js";

vi.mock("../services/nlParse.js", () => ({
  fetchParseModels: vi.fn(),
  parseTrade: vi.fn(),
}));
vi.mock("../services/trades.js", () => ({ bookTrade: vi.fn() }));

const PARSED = {
  model: "rule-based",
  draft: {},
  raw: {},
  trade: {
    instrument_type: "SPOT",
    currency_pair: "EURUSD",
    direction: "BUY",
    notional_1: 1000000,
    currency_1: "EUR",
    currency_2: "USD",
    counterparty: "BANK_A",
    instrument_details: {
      instrument_type: "SPOT",
      rate: 1.085,
      settlement_date: "2026-08-25",
    },
  },
};

describe("NlTradeEntry", () => {
  beforeEach(() => {
    fetchParseModels.mockReset();
    parseTrade.mockReset();
    bookTrade.mockReset();
    fetchParseModels.mockResolvedValue([
      { id: "rule-based", label: "Rule-based baseline", kind: "baseline" },
    ]);
  });

  it("renders the input panel and loads models", async () => {
    render(<NlTradeEntry onBooked={vi.fn()} />);
    expect(
      screen.getByRole("heading", { name: "Natural Language Trade" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Instruction")).toBeInTheDocument();
    await waitFor(() => expect(fetchParseModels).toHaveBeenCalled());
  });

  it("parses an instruction and shows a confirmation review", async () => {
    parseTrade.mockResolvedValue(PARSED);
    const user = userEvent.setup();
    render(<NlTradeEntry onBooked={vi.fn()} />);

    fireEvent.change(screen.getByLabelText("Instruction"), {
      target: { value: "Buy 1 million euros against dollars, spot at 1.085" },
    });
    await user.click(screen.getByRole("button", { name: "Parse & Review" }));

    expect(parseTrade).toHaveBeenCalledWith(
      "Buy 1 million euros against dollars, spot at 1.085",
      "rule-based",
    );
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "Review Parsed Trade" }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("EURUSD")).toBeInTheDocument();
    expect(screen.getByText("1.085")).toBeInTheDocument();
  });

  it("books the parsed trade on confirm and calls onBooked", async () => {
    parseTrade.mockResolvedValue(PARSED);
    bookTrade.mockResolvedValue({ trade_id: "t1", currency_pair: "EURUSD" });
    const onBooked = vi.fn();
    const user = userEvent.setup();
    render(<NlTradeEntry onBooked={onBooked} />);

    fireEvent.change(screen.getByLabelText("Instruction"), {
      target: { value: "Buy 1 million euros against dollars, spot at 1.085" },
    });
    await user.click(screen.getByRole("button", { name: "Parse & Review" }));
    await waitFor(() => screen.getByRole("heading", { name: "Review Parsed Trade" }));
    await user.click(screen.getByRole("button", { name: "Confirm & Book" }));

    await waitFor(() => expect(bookTrade).toHaveBeenCalled());
    expect(bookTrade.mock.calls[0][0]).toEqual(PARSED.trade);
    expect(onBooked).toHaveBeenCalledTimes(1);
  });
});
