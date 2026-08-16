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

| Command            | Purpose                                |
| ------------------ | -------------------------------------- |
| `npm run dev`      | Start the Vite dev server              |
| `npm run build`    | Production build to `dist/`            |
| `npm run preview`  | Preview the production build           |
| `npm run lint`     | Run ESLint (flat config)               |
| `npm run format`   | Format with Prettier                   |
| `npm run test`     | Run Vitest once (CI)                   |
| `npm run test:watch` | Run Vitest in watch mode             |

## Testing

Unit/component tests use [Vitest](https://vitest.dev) + [React Testing Library](https://testing-library.com/react) (jsdom). No backend or browser needed.

```bash
npm test             # run once
npm run test:watch   # re-run on changes
```

Test files live next to the code they cover (`*.test.js` / `*.test.jsx`) and are grouped by layer:

| Layer | File | What it covers |
| ----- | ---- | -------------- |
| services | `src/services/api.test.js` | GET/POST behaviour, non-2xx and network failures against a mocked `fetch` |
| hooks | `src/hooks/useTrades.test.jsx`, `useBookTrade.test.jsx` | success + error state transitions (services mocked) |
| components | `src/components/TradeBlotter.test.jsx` | empty hint, trade rows, error message |
| app | `src/App.test.jsx` | the three-panel layout renders |

Vitest config lives in `vite.config.js` (`test` block), shared setup in `src/test/setup.js`.

## Structure

```
src/
  components/   Presentational UI (PascalCase .jsx)
  hooks/        Data-fetching hooks (useMarketRates, useTrades, useBookTrade)
  services/     API wrappers (api base client, marketData, trades)
  test/         Vitest setup file
  App.jsx       Three-panel composition
  index.css     Global styles (trading-terminal theme)
```
