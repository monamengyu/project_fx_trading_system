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

`trade_date` and `status` are server-assigned — `trade_date` defaults to today, `status` starts at `PENDING_CONFIRMATION`. Neither can be set by the client on create.

### `GET /trades`
List all trades.

**Response `200 OK`**: a bare JSON array of trade objects (same shape as the `POST` response). Filtering/pagination is not yet implemented.

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

---

## Natural Language Trade Entry

### `POST /api/v1/nl/parse`
Send raw natural language text; returns a structured but **unconfirmed** trade object for the frontend to display back to the user.

**Request**
```json
{ "text": "Buy 1 million EUR against USD spot with Bank A" }
```

**Response `200 OK`**
```json
{
  "parse_id": "uuid",
  "parsed_trade": {
    "instrument_type": "SPOT",
    "currency_pair": "EURUSD",
    "direction": "BUY",
    "currency_1": "EUR",
    "notional_1": 1000000,
    "currency_2": "USD",
    "notional_2": null,
    "counterparty": "BANK_A",
    "instrument_details": { "rate": null, "settlement_date": null }
  },
  "confidence_flags": [
    { "field": "notional_2", "message": "not stated; derive from live rate" },
    { "field": "instrument_details.rate", "message": "not stated; requires live market rate" }
  ]
}
```

**Response `422 Unprocessable Entity`** if input can't be parsed into any valid trade shape.

### `POST /api/v1/nl/confirm`
Confirm a previously parsed trade (referenced by `parse_id`), optionally with user corrections, and book it.

**Request**
```json
{
  "parse_id": "uuid",
  "corrected_trade": {
    "instrument_details": { "rate": 1.0862, "settlement_date": "2026-08-01" },
    "notional_2": 1086200
  }
}
```

**Response `201 Created`**: full booked trade object (`status: "BOOKED"`)

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
Streams live rate updates to subscribed clients.

**Server → Client message**
```json
{ "pair": "EURUSD", "rate": 1.0863, "as_of": "2026-07-29T10:15:05Z" }
```

### `WS /ws/positions`
Streams live mark-to-market (MTM) position updates.

**Server → Client message**
```json
{ "trade_id": "uuid", "mtm_value": 1250.50, "as_of": "2026-07-29T10:15:05Z" }
```
