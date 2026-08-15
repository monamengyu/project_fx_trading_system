# FX Trading System — Frontend

React (Vite) frontend for the FX trading system, with a three-panel layout:
market data rates, trade blotter, and new-trade entry. All API calls are
centralised under `src/services/` and never called directly from components
(see `docs/coding_standards.md`).

## Requirements

- Node.js 18+ (20+ recommended)

## Local development

```bash
npm install
npm run dev      # starts Vite on http://localhost:3000
```

The app talks to the backend at `VITE_API_URL` (default `http://localhost:8000`):

```bash
VITE_API_URL=http://localhost:8000 npm run dev
```

With Docker (from the repo root):

```bash
docker compose up --build
```

Backend is exposed at `http://localhost:8000`, frontend at `http://localhost:3000`.

## Scripts

| Command           | Purpose                              |
| ----------------- | ------------------------------------ |
| `npm run dev`     | Start the Vite dev server            |
| `npm run build`   | Production build to `dist/`          |
| `npm run preview` | Preview the production build         |
| `npm run lint`    | Run ESLint (flat config)             |
| `npm run format`  | Format with Prettier                 |

## Structure

```
src/
  components/   Presentational UI (PascalCase .jsx)
  hooks/        Data-fetching hooks (useMarketRates, useTrades, useBookTrade)
  services/     API wrappers (api base client, marketData, trades)
  App.jsx       Three-panel composition
  index.css     Global styles (trading-terminal theme)
```
