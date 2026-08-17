import { render, screen } from "@testing-library/react";
import { TradeBlotter } from "./TradeBlotter.jsx";

describe("TradeBlotter", () => {
  it("shows a hint when there are no trades", () => {
    render(
      <TradeBlotter trades={[]} loading={false} error={null} onRefresh={() => {}} />,
    );
    expect(screen.getByText("No trades booked yet.")).toBeInTheDocument();
  });

  it("renders trade rows with the new columns", () => {
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
    render(
      <TradeBlotter
        trades={[trade]}
        loading={false}
        error={null}
        onRefresh={() => {}}
      />,
    );
    expect(screen.getByText("abc-123")).toBeInTheDocument();
    expect(screen.getByText("SPOT")).toBeInTheDocument();
    expect(screen.getByText("EURUSD")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("1.085")).toBeInTheDocument();
    expect(screen.getByText("EUR")).toBeInTheDocument();
    expect(screen.getByText("1000000")).toBeInTheDocument();
    expect(screen.getByText("USD")).toBeInTheDocument();
    expect(screen.getByText("1085000")).toBeInTheDocument();
    expect(screen.getByText("2026-08-19")).toBeInTheDocument();
    expect(screen.getByText("BANK_A")).toBeInTheDocument();
    expect(screen.getByText("BOOKED")).toBeInTheDocument();
  });

  it("shows an error when the request fails", () => {
    render(
      <TradeBlotter trades={[]} loading={false} error="boom" onRefresh={() => {}} />,
    );
    expect(screen.getByText("boom")).toBeInTheDocument();
  });
});
