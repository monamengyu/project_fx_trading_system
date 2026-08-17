import { fireEvent, render, screen } from "@testing-library/react";
import { NewTradeForm } from "./NewTradeForm.jsx";
import userEvent from "@testing-library/user-event";
import { bookTrade } from "../services/trades.js";

vi.mock("../services/trades.js", () => ({ bookTrade: vi.fn() }));

async function fillAndReview(user) {
  fireEvent.change(screen.getByLabelText("Settlement Date"), {
    target: { value: "2026-08-19" },
  });
  await user.click(screen.getByRole("button", { name: "Review Trade" }));
}

describe("NewTradeForm", () => {
  beforeEach(() => {
    bookTrade.mockReset();
  });

  it("shows a confirmation review before booking", async () => {
    const user = userEvent.setup();
    render(<NewTradeForm onBooked={vi.fn()} />);

    await fillAndReview(user);

    expect(screen.getByRole("heading", { name: "Confirm Trade" })).toBeInTheDocument();
    expect(screen.getByText("EURUSD")).toBeInTheDocument();
    expect(screen.getByText(/1,085,000/)).toBeInTheDocument(); // derived counter leg
  });

  it("books on confirm and calls onBooked", async () => {
    bookTrade.mockResolvedValue({ trade_id: "1", status: "PENDING_CONFIRMATION" });
    const onBooked = vi.fn();
    const user = userEvent.setup();
    render(<NewTradeForm onBooked={onBooked} />);

    await fillAndReview(user);
    await user.click(screen.getByRole("button", { name: "Confirm & Book" }));

    expect(bookTrade).toHaveBeenCalledTimes(1);
    expect(bookTrade.mock.calls[0][0].notional_2).toBe(1085000);
    expect(onBooked).toHaveBeenCalledTimes(1);
  });

  it("goes back to the form without booking", async () => {
    const user = userEvent.setup();
    render(<NewTradeForm onBooked={vi.fn()} />);

    await fillAndReview(user);
    await user.click(screen.getByRole("button", { name: "Back" }));

    expect(screen.getByRole("heading", { name: "New Trade" })).toBeInTheDocument();
    expect(bookTrade).not.toHaveBeenCalled();
  });
});
