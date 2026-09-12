# project_fx_trading_system

Foreign Exchange Trading System Supporting Natural Language Trade Entry Built in Python.

A full-stack FX trading desk application: live market rates, position summaries
with option greeks and mark-to-market P&L, a trade blotter covering the full
trade lifecycle (book → confirm / amend / cancel → mature), and natural-language
trade entry that converts a plain-English instruction into a validated trade.

## Contents

- [Features](#features)
- [Architecture](#architecture)
- [Repository layout](#repository-layout)
- [API overview](#api-overview)
- [Requirements](#requirements)
- [Quick start (Docker)](#quick-start-docker)
- [Local development](#local-development)
  - [Backend](#backend)
  - [Frontend](#frontend)
- [Configuration](#configuration)
- [Database & migrations](#database--migrations)
- [Testing](#testing)
- [Documentation](#documentation)
- [Continuous integration](#continuous-integration)

## Features

- **Market data** — supported FX pairs with rates from the Frankfurter API,
  cached server-side and pushed to the browser over WebSocket.
- **Positions** — net position per currency pair: notional totals, net delta /
  gamma / vega / theta, and unrealised P&L (mark to market, converted to USD),
  streamed live.
- **Trade blotter** — filterable trade list with the full lifecycle (confirm,
  amend, cancel, mature) backed by an append-only state history.
- **New trade form** — structured booking of SPOT, FORWARD and OPTION trades.
- **NL trade entry** — parses a plain-English instruction into a validated trade
  draft for review, then books it. The model is selectable: the deterministic
  rule-based baseline, hosted models via OpenRouter, or local models via Ollama.
  The original instruction is stored as the trade comment, and token usage plus
  elapsed time are reported with the parsed ticket.
- **Pricing** — Black-Scholes option pricing with greeks.

## Architecture

| Layer        | Technology                                                                            |
| ------------ | ------------------------------------------------------------------------------------- |
| Database     | PostgreSQL 16, SQLAlchemy 2 (async) + `asyncpg`, Alembic migrations                    |
| Backend      | Python 3.12, FastAPI, Uvicorn, Pydantic v2                                             |
| Frontend     | React 18, Vite 5, plain CSS (trading-terminal theme)                                   |
| Realtime     | WebSockets (`/ws/market-data`, `/ws/positions`)                                        |
| Market data  | [Frankfurter](https://www.frankfurter.app/) API with an in-process TTL cache           |
| LLM parsing  | OpenRouter (hosted) and/or Ollama (local), plus a deterministic rule-based baseline     |
| Tests        | `pytest` (backend), Vitest + React Testing Library (frontend)                          |

## Repository layout

```
.
├── backend/                  FastAPI application
│   ├── app/
│   │   ├── api/              Routers, one per resource, aggregated in router.py
│   │   ├── core/             Settings (pydantic-settings)
│   │   ├── db/               Async SQLAlchemy engine and session
│   │   ├── models/           SQLAlchemy models (Trade, TradeStateLog)
│   │   ├── schemas/          Pydantic request/response models
│   │   └── services/         Business logic: pricing, market data, NL parsing,
│   │                         trade lifecycle, MTM, business calendar
│   ├── migrations/           Alembic environment and versioned migrations
│   ├── tests/                pytest suite (mirrors app/)
│   ├── alembic.ini
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/                 React + Vite dashboard
│   ├── src/
│   │   ├── components/       Presentational UI (PascalCase .jsx)
│   │   ├── hooks/            Data-fetching and WebSocket hooks
│   │   ├── services/         API call wrappers
│   │   ├── test/             Vitest setup
│   │   └── utils/            Shared helpers (date formatting)
│   ├── Dockerfile
│   ├── package.json
│   └── vite.config.js
├── docs/                     api_contracts.md, schema_design.md, coding_standards.md
├── .github/workflows/ci.yml  CI: backend pytest, frontend lint/test/build
├── docker-compose.yml        postgres + backend + frontend
├── pytest.ini                Shared pytest config (runs from root or backend/)
└── .env.example              Template for the Compose environment
```

## API overview

| Router        | Endpoints                                                                 |
| ------------- | ------------------------------------------------------------------------- |
| Trades        | `POST /trades`, `GET /trades`, `GET /trades/{id}`, `GET /trades/{id}/history`, `POST /trades/{id}/confirm`, `POST /trades/{id}/cancel`, `POST /trades/{id}/amend` |
| Positions     | `GET /positions`                                                          |
| Market data   | `GET /market-data/pairs`, `GET /market-data/rates`                        |
| Pricing       | `POST /pricing/options`                                                   |
| NL parse      | `GET /nl-parse/models`, `POST /nl-parse`                                  |
| Health        | `GET /health`, `GET /health/db`                                           |
| WebSocket     | `/ws/market-data`, `/ws/positions`                                        |

Full request/response contracts are in [docs/api_contracts.md](docs/api_contracts.md).

## Requirements

- Docker + Docker Compose (for the containerised path), **or**
- Python 3.12+ and Node.js 18+ (20+ recommended), plus a PostgreSQL 16 instance
- Optional: an [OpenRouter](https://openrouter.ai/) API key for hosted LLM models,
  and/or [Ollama](https://ollama.com/) running locally for local models

## Quick start (Docker)

From the repository root:

```bash
cp .env.example .env    # set POSTGRES_* and, if used, OPENROUTER_API_KEY
docker compose up --build
```

- Backend: <http://localhost:8000> (interactive docs at `/docs`)
- Frontend: <http://localhost:3000>

Migrations are **not** applied automatically, so run them once against the
running stack:

```bash
docker compose exec backend python -m alembic upgrade head
```

## Local development

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate         # Windows; use `source .venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
```

Create `backend/.env` containing at least `DATABASE_URL`, then apply migrations
and start the API:

```bash
python -m alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

> Alembic reads `DATABASE_URL` from the **process environment** (see
> `migrations/env.py`), not from `backend/.env`, so export it for migration
> commands. For example, in PowerShell set
> `$env:DATABASE_URL` to `postgresql://<user>:<password>@localhost:5432/<database>`.

CORS by default allows the Vite dev server on `http://localhost:3000`
(configurable via `CORS_ORIGINS`).

### Frontend

```bash
cd frontend
npm install
npm run dev      # starts Vite on http://localhost:3000
```

The app talks to the backend at `VITE_API_URL` (default `http://localhost:8000`):

```bash
VITE_API_URL=http://localhost:8000 npm run dev
```

#### Scripts

| Command              | Purpose                                |
| -------------------- | -------------------------------------- |
| `npm run dev`        | Start the Vite dev server              |
| `npm run build`      | Production build to `dist/`            |
| `npm run preview`    | Preview the production build           |
| `npm run lint`       | Run ESLint (flat config)               |
| `npm run format`     | Format with Prettier                   |
| `npm test`           | Run Vitest once (CI)                   |
| `npm run test:watch` | Run Vitest in watch mode               |

#### Structure

```
src/
  components/   Presentational UI (PascalCase .jsx)
  hooks/        Data-fetching + WebSocket hooks (useTrades, usePositions,
                useMarketRates, useBookTrade, useNlParse, ...)
  services/     API wrappers (api base client, trades, positions, marketData,
                pricing, nlParse)
  test/         Vitest setup file
  utils/        Shared helpers
  App.jsx       Dashboard composition
  index.css     Global styles (trading-terminal theme)
```

All API calls go through `src/services/` and are never made directly from
components (see [docs/coding_standards.md](docs/coding_standards.md)).

## Configuration

Docker Compose reads `POSTGRES_*` and `OPENROUTER_API_KEY` from the root `.env`
(see `.env.example`). The backend reads `backend/.env`:

| Variable                     | Default                                          | Purpose                                                        |
| ---------------------------- | ------------------------------------------------ | -------------------------------------------------------------- |
| `DATABASE_URL`               | — (required)                                     | PostgreSQL DSN; the async driver is added automatically         |
| `APP_NAME`                   | `FX Trading System`                              | FastAPI application title                                      |
| `CORS_ORIGINS`               | `["http://localhost:3000", "http://127.0.0.1:3000"]` | Browser origins allowed to call the API                     |
| `MARKET_DATA_CACHE_TTL_SECONDS` | `3600`                                        | Market-data cache TTL                                           |
| `NL_PARSE_DEFAULT_MODEL`     | `rule-based`                                     | Model preselected for NL parsing                                |
| `OPENROUTER_API_KEY`         | — (unset)                                        | Enables the hosted OpenRouter models in the model dropdown      |
| `OPENROUTER_BASE_URL`        | `https://openrouter.ai/api/v1`                   | OpenRouter gateway URL                                          |
| `OPENROUTER_MODELS`          | built-in list                                    | JSON list of OpenRouter model IDs offered                       |
| `OLLAMA_BASE_URL`            | `http://localhost:11434/v1`                      | Ollama endpoint for local models                                |
| `OLLAMA_MODELS`              | built-in list                                    | JSON list of local Ollama model IDs offered                     |
| `LLM_REQUEST_TIMEOUT_SECONDS`| `120`                                            | LLM request timeout (cold model loads can be slow)              |

## Database & migrations

The schema is managed by Alembic under `backend/migrations/`. It is a generic
single-database configuration: `alembic.ini` sets `script_location = migrations`
and `migrations/env.py` loads `DATABASE_URL` from the environment.

```bash
cd backend
python -m alembic upgrade head                          # apply all migrations
python -m alembic revision --autogenerate -m "message"  # create a migration
python -m alembic current                               # show the applied revision
```

Every schema change must also be reflected in
[docs/schema_design.md](docs/schema_design.md) and, when structural, its ER diagram.

## Testing

### Backend (`pytest`)

`pytest.ini` at the repository root sets `testpaths = backend/tests`,
`pythonpath = backend` and async mode, so the suite runs from either the root or
`backend/`. The integration tests need a reachable PostgreSQL database.

```bash
python -m pytest -q            # from the repository root
# or
cd backend; python -m pytest -q
```

| Area                | Test files                                                                                          |
| ------------------- | --------------------------------------------------------------------------------------------------- |
| Booking & lifecycle | `test_booking_flow_integration.py`, `test_trade_lifecycle.py`, `test_settlement_rules.py`, `test_forward_booking.py` |
| API routers         | `test_trades_api.py`, `test_positions_api.py`, `test_pricing_api.py`, `test_market_data_api.py`, `test_websocket.py` |
| NL parsing          | `test_nl_parse.py`, `test_nl_parse_api.py`                                                          |
| Services            | `test_black_scholes.py`, `test_mtm.py`, `test_business_calendar.py`, `test_market_data_cache.py`, `test_frankfurter_client.py` |
| Schemas & database  | `test_instrument_details.py`, `test_db_roundtrip.py`                                                |

### Frontend (Vitest)

Unit and component tests use [Vitest](https://vitest.dev) with
[React Testing Library](https://testing-library.com/react) (jsdom) — no backend
or browser required. Test files live next to the code they cover, named
`*.test.js(x)`, and are grouped by layer:

| Layer      | Files                                                                                        | What it covers                                                  |
| ---------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| services   | `src/services/api.test.js`                                                                   | GET/POST behaviour, non-2xx and network failures against a mocked `fetch` |
| hooks      | `src/hooks/*.test.jsx`                                                                       | Success/error state transitions and WebSocket streams (services mocked) |
| components | `src/components/{TradeBlotter,PositionsPanel,NlTradeEntry,NewTradeForm,DateRangePicker}.test.jsx` | Rendering, empty hints and error messages for each panel  |
| app        | `src/App.test.jsx`                                                                           | The dashboard layout renders                                    |

```bash
cd frontend
npm test             # run once
npm run test:watch   # re-run on changes
```

Vitest config lives in `vite.config.js` (the `test` block); shared setup is in
`src/test/setup.js`.

## Documentation

Project documentation lives in [docs/](docs):

- [API contracts](docs/api_contracts.md) — endpoints, payloads and error shapes
- [Schema design](docs/schema_design.md) — tables, JSONB instrument details, ER diagram
- [Coding standards](docs/coding_standards.md) — backend/frontend conventions, git workflow

## Continuous integration

[.github/workflows/ci.yml](.github/workflows/ci.yml) runs on every push and pull request:

- **Backend** — spins up a PostgreSQL 16 service, installs `requirements.txt`,
  runs `alembic upgrade head`, then `pytest -q`.
- **Frontend** — `npm ci`, then `npm run lint`, `npm test` and `npm run build`.
