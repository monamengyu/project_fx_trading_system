# API Contracts

## Conventions

- Base path: none currently (all trade routes are unversioned, e.g. `/trades`); a version prefix such as `/api/v1` may be introduced later if/when needed
- Format: JSON request/response bodies (`Content-Type: application/json`)
- Auth: not in scope for this project; endpoints are unauthenticated
- Timestamps: ISO 8601 (`YYYY-MM-DDTHH:MM:SSZ`)
- Dates: ISO 8601 date only (`YYYY-MM-DD`)

## Standard Error Response

All error responses use this shape, regardless of endpoint:

```json
{
  "detail": [
    {
      "field": "currency_pair",
      "message": "unsupported currency pair"
    }
  ]
}
```

| Status Code | Meaning |
|---|---|
| 400 | Malformed request |
| 404 | Resource not found |
| 409 | State conflict (e.g. cancelling/amending a trade in an invalid state) |
| 422 | Validation error (field-level) |
| 500 | Unexpected server error |

---

## Trades

### `POST /trades`
Book a new trade directly (structured form entry, not via NL parsing).

**Request**
```json
{
  "instrument_type": "SPOT",
  "currency_pair": "EURUSD",
  "direction": "BUY",
  "currency_1": "EUR",
  "notional_1": 1000000,
  "currency_2": "USD",
  "notional_2": 1085000,
  "counterparty": "BANK_A",
  "comment": "",
  "instrument_details": {
    "instrument_type": "SPOT",
    "rate": 1.085,
    "settlement_date": "2026-08-01"
  }
}
```

**Response `201 Created`**
```json
{
  "trade_id": "uuid",
  "instrument_type": "SPOT",
  "currency_pair": "EURUSD",
  "direction": "BUY",
  "currency_1": "EUR",
  "notional_1": 1000000,
  "currency_2": "USD",
  "notional_2": 1085000,
  "trade_date": "2026-07-29",
  "counterparty": "BANK_A",
  "status": "PENDING_CONFIRMATION",
  "comment": "",
  "instrument_details": { "instrument_type": "SPOT", "rate": 1.085, "settlement_date": "2026-08-01" }
}
```

`trade_date` and `status` are server-assigned — `trade_date` defaults to today (rolled forward to the next business day if today is a weekend, so `trade_date` is always a business day), `status` starts at `PENDING_CONFIRMATION`. Neither can be set by the client on create.

**Settlement-date rule**: settlement dates must be business days (Mon-Fri, weekends excluded). SPOT trades must settle between the trade date and the spot value date (trade date + 2 business days). Settlement dates beyond the spot value date are only allowed for FORWARD trades. Violations return `422 Unprocessable Entity`.

### `GET /trades`
List trades (the blotter) with optional filters and offset/limit pagination. All query params are optional.

| Query param | Type | Meaning |
|---|---|---|
| `instrument_type` | enum | SPOT, FORWARD, OPTION |
| `currency_pair` | enum | e.g. EURUSD |
| `status` | enum | PENDING_CONFIRMATION, BOOKED, CANCELLED, MATURED |
| `trade_date_from` | date | Inclusive lower bound on `trade_date` (YYYY-MM-DD) |
| `trade_date_to` | date | Inclusive upper bound on `trade_date` (YYYY-MM-DD) |
| `settlement_date_from` | date | Inclusive lower bound on `instrument_details.settlement_date` (YYYY-MM-DD) |
| `settlement_date_to` | date | Inclusive upper bound on `instrument_details.settlement_date` (YYYY-MM-DD) |
| `limit` | int | Max rows to return (default 50) |
| `offset` | int | Rows to skip (default 0) |

**Response `200 OK`**: a bare JSON array of trade objects (same shape as the `POST` response), ordered by `trade_date` descending.

### `GET /trades/{trade_id}`
Get a single trade by ID.

**Response `200 OK`**: full trade object
**Response `404 Not Found`** if trade_id doesn't exist

### `GET /trades/{trade_id}/history`
Get the append-only lifecycle log for a trade. Every state transition (including the initial booking) appends an immutable row to the `trade_state` log.

**Response `200 OK`**
```json
{
  "trade_id": "uuid",
  "history": [
    {
      "state_id": 1,
      "state": "PENDING_CONFIRMATION",
      "changed_at": "2026-07-29T10:15:00Z",
      "changed_by": "system",
      "notes": ""
    }
  ]
}
```

**Response `404 Not Found`** if `trade_id` doesn't exist

Booking a trade via `POST /trades` creates the trade with `status: PENDING_CONFIRMATION` and appends the matching initial entry to its lifecycle log (`changed_by: "system"`).

### `POST /trades/{trade_id}/cancel`
Cancel a trade. Allowed from `PENDING_CONFIRMATION` or `BOOKED`. The trade row is **not deleted** — `status` becomes `CANCELLED` and a `CANCELLED` entry is appended to the lifecycle log.

**Request**
```json
{ "comment": "not agreed" }
```

**Response `200 OK`**: full trade object with `status: "CANCELLED"`
**Response `404 Not Found`** if `trade_id` doesn't exist
**Response `409 Conflict`** if the trade is not in a cancellable state (e.g. already `CANCELLED`)

### `POST /trades/{trade_id}/confirm`
Confirm a pending trade: `status` becomes `BOOKED` and a `BOOKED` entry is appended to the lifecycle log. (This is what moves a trade into a position.)

**Request**
```json
{ "comment": "confirmed" }
```

**Response `200 OK`**: full trade object with `status: "BOOKED"`
**Response `404 Not Found`** if `trade_id` doesn't exist
**Response `409 Conflict`** if the trade is not `PENDING_CONFIRMATION`

### `POST /trades/{trade_id}/amend`
Amend a booked trade (notional and/or comment). The trade's `status` stays `BOOKED` and an `AMENDED` entry is appended to the lifecycle log.

**Request** (at least one field required)
```json
{ "notional_1": 2000000, "comment": "increased size" }
```

**Response `200 OK`**: full trade object with the amended fields
**Response `404 Not Found`** if `trade_id` doesn't exist
**Response `409 Conflict`** if the trade is not `BOOKED`
**Response `422 Unprocessable Entity`** if the body is empty

---

## Positions

### `GET /positions`
Position summary per currency pair, aggregated from confirmed (`BOOKED`) trades. Both currency legs are always reported: `*_notional_1` in `currency_1`, `*_notional_2` in `currency_2`. `net_notional_*` is BUY notional − SELL notional. The currency_2 leg uses a trade's explicit `notional_2` when present, otherwise it is derived as `notional_1 × rate`; if the rate is unavailable and no explicit `notional_2` exists, the currency_2 fields are `null`. `mtm_value` marks the net position to market using the current rate (in currency_2), and is `null` if the rate is unavailable.

**Response `200 OK`**
```json
[
  {
    "currency_pair": "EURUSD",
    "currency_1": "EUR",
    "currency_2": "USD",
    "count": 2,
    "total_notional_1": 1400000.0,
    "total_notional_2": 1610000.0,
    "net_notional_1": 600000.0,
    "net_notional_2": 690000.0,
    "mtm_value": 690000.0
  }
]
```

PENDING_CONFIRMATION, CANCELLED and MATURED trades are excluded from positions.

---

## Market Data

### `GET /market-data/rates`
Source: [Frankfurter](https://api.frankfurter.dev) (free, wraps ECB daily reference rates). Rates update once per ECB business day, so `as_of` is a date, not a timestamp.

**Query params:** `pair` (e.g. `EURUSD`, `GBPUSD`, `USDJPY`)

**Response `200 OK`**
```json
{ "pair": "EURUSD", "rate": 1.0862, "as_of": "2026-07-29" }
```

**Response `422 Unprocessable Entity`** if `pair` isn't a supported `CurrencyPair`
**Response `502 Bad Gateway`** if the upstream Frankfurter request fails

**Caching behaviour**

Rates are cached in memory per currency pair for `market_data_cache_ttl_seconds`
(default `3600`, configurable via env/`.env`). While a cached rate is fresh,
repeated calls are served from the cache and never hit the upstream provider.

If the upstream Frankfurter request fails and a previously cached rate exists
(even one that has expired), the stale rate is returned with `200 OK` using its
original `as_of` date — the response stays available and the date makes the
staleness transparent. `502 Bad Gateway` is only returned when the upstream
fails and no cached rate exists for the pair.

---

## WebSocket Endpoints

### `WS /ws/market-data`
Streams live rate updates to subscribed clients. The backend pushes a message per supported pair roughly every 5 seconds while at least one client is connected.

**Server → Client message**
```json
{ "pair": "EURUSD", "rate": 1.0863, "as_of": "2026-08-14" }
```

`as_of` is the Frankfurter reference-rate date (rates update once per ECB business day), matching the REST `GET /market-data/rates` response.

### `WS /ws/positions`
Streams live mark-to-market (MTM) position updates.

**Server → Client message**
```json
{ "trade_id": "uuid", "mtm_value": 1250.50, "as_of": "2026-07-29T10:15:05Z" }
```

## Natural language trade entry

### `GET /nl-parse/models`
List the models selectable for NL trade parsing. The `rule-based` baseline is
always present; hosted LLM models (served through OpenRouter) are only listed
when `OPENROUTER_API_KEY` is configured, plus the local `ollama-llama3`.

**Response `200 OK`**: array of `{ "id", "label", "kind" }`.

### `POST /nl-parse`
Parse a plain-English trade instruction into a validated trade payload (same
shape as `POST /trades`), ready for the user to confirm before booking. No
trade is persisted by this endpoint.

**Request**
```json
{ "text": "Buy 1 million euros against dollars, spot at 1.085", "model": "rule-based" }
```

**Response `200 OK`**
```json
{
  "model": "rule-based",
  "draft": { "...": "normalised NL interpretation" },
  "trade": { "...": "validated TradeCreate payload (confirmed before booking)" },
  "raw": { "...": "raw model output, for model evaluation" }
}
```

**Response `400 Bad Request`** if `model` is unknown
**Response `422 Unprocessable Entity`** if the text cannot be parsed into a valid trade
**Response `502 Bad Gateway`** if the selected LLM provider fails

Models: `rule-based` (baseline, always), one entry per ID in the
`OPENROUTER_MODELS` env list (JSON) served via OpenRouter — e.g.
`openai/gpt-4o-mini`, `anthropic/claude-sonnet-4-5`,
`google/gemini-2.0-flash-001` — listed only when `OPENROUTER_API_KEY` is set,
and `ollama-llama3` (local, always). Missing rates are resolved from the live market rate; missing
option fields get defaults (premium 0, delivery = expiry, EUROPEAN style).
