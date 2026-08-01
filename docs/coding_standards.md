# Coding Standards

## Backend (Python / FastAPI)

| Concern | Standard |
|---|---|
| Formatter | `black` |
| Linter | `ruff` |
| Type checking | `mypy` (optional, recommended for models/schemas) |
| Naming | `snake_case` for functions/variables; `PascalCase` for classes (Pydantic models, SQLAlchemy models) |
| Async | All I/O-bound functions (DB queries, LLM API calls, market data fetches) must be `async def`, using `asyncpg`/SQLAlchemy async session |
| Validation | All request/response bodies defined as Pydantic models — no raw dict handling in route functions |
| File layout | One router per resource under `app/api/` (e.g. `trades.py`, `nl_parse.py`, `market_data.py`) |
| Imports | Standard library, then third-party, then local imports — each group separated by a blank line |

### Example function signature style
```python
async def get_trade(trade_id: UUID, db: AsyncSession) -> TradeResponse:
    ...
```

## Frontend (React)

| Concern | Standard |
|---|---|
| Formatter | `Prettier` |
| Linter | `ESLint` |
| Component naming | `PascalCase` (e.g. `TradeBlotter.jsx`) |
| Function/variable naming | `camelCase` |
| Folder structure | `components/`, `hooks/`, `services/` (API call wrappers), `pages/` |
| API calls | Centralised in `services/`, never called directly inside components |
| State management | React hooks (`useState`, `useReducer`); avoid prop drilling beyond 2 levels — lift to context if needed |

## Git Conventions

### Commit messages (Conventional Commits style)
```
feat: add NL parse endpoint
fix: correct notional_2 calculation on forward trades
docs: update API contracts for trade confirmation flow
chore: bump FastAPI version
```

### Branch naming
```
release-1-foundation
release-2-trading
release-3-nl-entry
feature/nl-parse-endpoint
fix/websocket-reconnect
```

### Pull requests (if used, even solo)
- One logical change per PR
- PR description should reference which Release it belongs to

## Documentation

- Every new API endpoint added to code must also be reflected in `docs/api_contracts.md`
- Every schema change must be reflected in `docs/schema_design.md` and, if structural, the ER diagram

## Testing (baseline expectation)

- Backend: `pytest`, tests under `backend/tests/`, mirroring `app/` structure
- Minimum: one test per endpoint covering the success path and one validation-failure path
