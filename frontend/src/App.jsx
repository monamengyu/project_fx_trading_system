import { Header } from "./components/Header.jsx";
import { Layout } from "./components/Layout.jsx";
import { MarketRatesPanel } from "./components/MarketRatesPanel.jsx";
import { NewTradeForm } from "./components/NewTradeForm.jsx";
import { PositionsPanel } from "./components/PositionsPanel.jsx";
import { TradeBlotter } from "./components/TradeBlotter.jsx";
import { useTrades } from "./hooks/useTrades.js";

export default function App() {
  const { trades, loading, error, refresh } = useTrades();

  return (
    <div className="app">
      <Header />
      <Layout
        leftTop={<MarketRatesPanel />}
        leftBottom={<PositionsPanel />}
        center={
          <TradeBlotter
            trades={trades}
            loading={loading}
            error={error}
            onRefresh={refresh}
          />
        }
        right={<NewTradeForm onBooked={refresh} />}
      />
    </div>
  );
}
