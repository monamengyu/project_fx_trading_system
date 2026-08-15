import { Header } from "./components/Header.jsx";
import { Layout } from "./components/Layout.jsx";
import { MarketRatesPanel } from "./components/MarketRatesPanel.jsx";
import { NewTradeForm } from "./components/NewTradeForm.jsx";
import { TradeBlotter } from "./components/TradeBlotter.jsx";
import { useTrades } from "./hooks/useTrades.js";

export default function App() {
  const { trades, loading, error, refresh } = useTrades();

  return (
    <div className="app">
      <Header />
      <Layout
        left={<MarketRatesPanel />}
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
