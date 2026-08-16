import { render, screen } from "@testing-library/react";
import { TradeBlotter } from "./TradeBlotter.jsx";

describe("TradeBlotter", () => {
  it("shows a hint when there are no trades", () => {
    render(
      <TradeBlotter trades={[]} loading={false} error={null} onRefresh={() => {}} />,
    );
    expect(screen.getByText("No trades booked yet.")).toBeInTheDocument();
  });

  it("renders trade rows", () => {
    const trade = {
      trade_id: "abc-123",
      currency_pair: "EURUSD",
      direction: "BUY",
      notional_1: 1000000,
      currency_1: "EUR",
      counterparty: "BANK_A",
      status: "BOOKED",
      trade_date: "2026-08-16",
    };
    render(
      <TradeBlotter
        trades={[trade]}
        loading={false}
        error={null}
        onRefresh={() => {}}
      />,
    );
    expect(screen.getByText("EURUSD")).toBeInTheDocument();
    expect(screen.getByText("1000000 EUR")).toBeInTheDocument();
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
