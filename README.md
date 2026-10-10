# project_fx_trading_system

Foreign Exchange Trading System Supporting Natural Language Trade Entry.

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
  - [Services and ports](#services-and-ports)
  - [First run](#first-run)
  - [Common commands](#common-commands)
  - [What the images are](#what-the-images-are)
  - [Docker troubleshooting](#docker-troubleshooting)
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

### Services and ports

| Service    | Container     | Host port | Notes                                                    |
| ---------- | ------------- | --------- | -------------------------------------------------------- |
| Backend    | `fx_backend`  | 8000      | FastAPI on Uvicorn; interactive docs at `/docs`           |
| Frontend   | `fx_frontend` | 3000      | Vite dev server                                           |
| PostgreSQL | `fx_postgres` | 5432      | data persists in the `pgdata` volume                      |

All three restart unless stopped, and the backend waits for the database health
check before it starts. The backend container is itself health-checked on
`/health`, so `docker compose ps` reports the real state rather than just
"running".

### First run

From the repository root:

```bash
cp .env.example .env    # set POSTGRES_* and, if used, OPENROUTER_API_KEY
docker compose up --build
```

The first build takes a few minutes; later starts take seconds. Then apply the
schema once:

```bash
docker compose exec backend python -m alembic upgrade head
```

Migrations are **not** applied automatically, so this step is required after the
first start and after `docker compose down -v`. Without it the API starts but
every trade and position request fails, because the tables do not exist.

Confirm both sides are up before opening the dashboard:

```bash
curl localhost:8000/health      # the API process
curl localhost:8000/health/db   # the API reaching the database
```

The dashboard is at <http://localhost:3000>. The browser calls the API on
`localhost:8000` directly (`VITE_API_URL` in `docker-compose.yml`), so no proxy
sits between them.

### Common commands

| Task                                   | Command                                           |
| -------------------------------------- | ------------------------------------------------- |
| Follow the backend logs                | `docker compose logs -f backend`                  |
| Rebuild after a dependency change      | `docker compose up --build`                       |
| Stop, keeping the database contents    | `docker compose down`                             |
| Stop and delete the database           | `docker compose down -v`                          |
| Shell inside the backend               | `docker compose exec backend sh`                  |

Dependency changes need the rebuild: both images install their dependencies at
build time, and the source directories are mounted over the images at run time.

Run the test suites on the host rather than in the container. The backend image
does not install `pytest`, only `pytest-asyncio`, which the application itself
needs; and the suite empties the trade book before every test, so running it
against the containerised database would delete the trades the dashboard is
showing. See [Testing](#testing) for the local commands.

### What the images are

Both are development images, not release images. The backend image installs
`requirements.txt` and runs Uvicorn with `--reload` over the bind-mounted
`backend/` directory. The frontend image installs from the lockfile and runs the
Vite dev server over the bind-mounted `frontend/`, keeping `node_modules` inside
the container so the host tree is left alone. Source edits are therefore picked
up without a rebuild.

Two consequences are worth stating plainly, because "deploy with Docker" can
mean more than this stack does. There is no built frontend bundle served by a
static server, and no reverse proxy, TLS or secret management: the stack is
intended for local demonstration and for the environment validation reported in
the write-up, not for an internet-facing deployment. The database port is also
published to the host, which is convenient for inspection with `psql` and should
be closed for anything else.

### Docker troubleshooting

| Symptom | Cause and fix |
| ------- | ------------- |
| `alembic upgrade head` fails with `ModuleNotFoundError: No module named 'psycopg'` | `requirements.txt` pins SQLAlchemy below 2.1 on purpose: a plain `postgresql://` URL resolves to the psycopg v3 driver from 2.1 onward, while the image installs `psycopg2-binary`. Rebuild after changing dependencies, and do not lift the pin without switching the URL scheme to `postgresql+psycopg2://`. |
| Every trade or position request returns 500 | The schema was never applied. Run the migration command above against the running stack. |
| Local models fail with a connection error | Ollama runs on the host, not in the stack. `docker-compose.yml` points the backend at `http://host.docker.internal:11434/v1` and adds `extra_hosts: host-gateway` for this reason. On Windows, Ollama must be running inside WSL; if it listens on another port, set `OLLAMA_BASE_URL` in `docker-compose.yml`. |
| Hosted models are missing from the model dropdown | `OPENROUTER_API_KEY` is unset in the root `.env`. `GET /nl-parse/models` lists them only when a key is present. |
| `port is already allocated` | Another process holds 3000, 8000 or 5432. Change the host side of the mapping in `docker-compose.yml`, for example `"8001:8000"`, and use the new port in the browser. |
| The dashboard loads but requests are blocked by CORS | The origin the browser uses must appear in `CORS_ORIGINS`, which defaults to `http://localhost:3000` and `http://127.0.0.1:3000`. Which file wins is worth knowing: the container reads `backend/.env` through the mount, but environment variables set in `docker-compose.yml` take precedence, so `DATABASE_URL` comes from Compose while `CORS_ORIGINS` comes from `backend/.env` or its default. |

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
