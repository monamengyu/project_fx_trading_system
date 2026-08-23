import { Header } from "./components/Header.jsx";
import { Layout } from "./components/Layout.jsx";
import { MarketRatesPanel } from "./components/MarketRatesPanel.jsx";
import { NewTradeForm } from "./components/NewTradeForm.jsx";
import { NlTradeEntry } from "./components/NlTradeEntry.jsx";
import { PositionsPanel } from "./components/PositionsPanel.jsx";
import { TradeBlotter } from "./components/TradeBlotter.jsx";
import { useTrades } from "./hooks/useTrades.js";

export default function App() {
  const { trades, loading, error, refresh, filters, setFilters } = useTrades();

  return (
    <div className="app">
      <Header />
      <Layout
        topLeft={<MarketRatesPanel />}
        topCenter={<PositionsPanel />}
        topRight={<NewTradeForm onBooked={refresh} />}
        bottomLeft={
          <TradeBlotter
            trades={trades}
            loading={loading}
            error={error}
            onRefresh={refresh}
            filters={filters}
            setFilters={setFilters}
          />
        }
        bottomRight={<NlTradeEntry onBooked={refresh} />}
      />
    </div>
  );
}
