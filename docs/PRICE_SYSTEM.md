# KisanQueue — Mandi Price Intelligence Subsystem

## 1. Subsystem Architecture Overview

The KisanQueue Mandi Price Subsystem provides real-time, cached, and fallback agricultural market price data sourced from the Government of India Open Government Data (OGD) platform (AGMARKNET dataset: `9ef84268-d588-465a-a308-a864a43d0070`).

```
                    ┌─────────────────────────────────────────┐
                    │   Client / Frontend / WhatsApp Bot     │
                    └───────────────────┬─────────────────────┘
                                        │
                                        ▼
                    ┌─────────────────────────────────────────┐
                    │    GET /v1/prices, /v1/prices/sync-status │
                    └───────────────────┬─────────────────────┘
                                        │
                                        ▼
                    ┌─────────────────────────────────────────┐
                    │          MandiPriceService              │
                    └───────┬─────────────────────────┬───────┘
                            │                         │
     [PRICE_PROVIDER=agmarknet]             [PRICE_PROVIDER=seed]
                            │                         │
                            ▼                         ▼
            ┌────────────────────────┐        ┌───────────────┐
            │  AgmarknetClient       │        │  Demo Cache   │
            │  (HTTPX + Retries)     │        │  (DB Seed)    │
            └───────┬────────────────┘        └───────┬───────┘
                    │                                 │
           Success  │  Failure                        │
                    ▼                                 │
            ┌───────────────┐                         │
            │  Normalizer   │                         │
            └───────┬───────┘                         │
                    │                                 │
                    ▼                                 │
    ┌───────────────────────────────┐                 │
    │  PostgreSQL: mandi_prices     │◄────────────────┘
    │  (Composite Natural Key:      │
    │   commodity, variety, market, │
    │   arrival_date, source)       │
    └───────────────────────────────┘
```

---

## 2. Provenance vs Delivery Status Separation

To prevent data ambiguity, KisanQueue strictly decouples **data origin (provenance)** from **transport mechanism (delivery status)**:

### 2.1 Data Origin (`source`)
Identifies where the market record originated. Stored permanently in the database:
- `AGMARKNET`: Official Government of India Open Government Data platform.
- `DEMO_SEED`: Realistic synthetic seed data loaded for local development, demonstrations, or sandboxed testing.

### 2.2 Delivery Status (`delivery_status`)
Identifies how the API response was fulfilled at runtime:
- `LIVE_API`: Fetched live from upstream data.gov.in in the current request transaction.
- `CACHE_HIT`: Retrieved from persistent local database cache within the fresh cache window (<= `PRICE_CACHE_TTL_HOURS`, default 6 hours).
- `FALLBACK`: Upstream live fetch failed (timeout, HTTP 429, HTTP 5xx, or network partition); degraded gracefully to local database records.
- `DEMO`: Served from persistent demo seed records under `PRICE_PROVIDER=seed` or mock mode.

---

## 3. Data Age vs Fetch/Cache Age

The subsystem measures and exposes two distinct dimensions of age:

1. **Data Age (`arrival_date` vs current date)**:
   - Reflects the calendar date of the physical market arrivals recorded by the Mandi board.
   - Example: On Monday morning, arrivals may still reflect Saturday's trading date.
2. **Fetch/Cache Age (`fetched_at` vs current time)**:
   - Reflects how recently KisanQueue queried the upstream registry or refreshed the local cache.
   - Example: Fetched 15 minutes ago (`fetched_at = 2026-09-10T02:00:00Z`).

### Freshness Classification (`freshness`)
- `LIVE`: Returned immediately from an in-flight upstream response.
- `RECENT_CACHE`: Stored record where `now() - fetched_at <= PRICE_CACHE_TTL_HOURS` (6 hours).
- `STALE_CACHE`: Stored record where `now() - fetched_at > PRICE_CACHE_TTL_HOURS` (used during upstream outages).
- `DEMO`: Seed / demo environment data.
- `NO_DATA`: No price records found in DB or upstream.

---

## 4. Database Schema & Natural Key Deduplication

### 4.1 Schema Definition (`mandi_prices` table)

| Column Name | Type | Modifiers | Description |
|---|---|---|---|
| `id` | `VARCHAR(36)` | PRIMARY KEY | Unique UUID identifier |
| `source` | `VARCHAR(30)` | NOT NULL, INDEX | Origin (`AGMARKNET`, `DEMO_SEED`) |
| `source_record_id` | `VARCHAR(100)` | NULLABLE | Upstream record ID if provided by source |
| `commodity` | `VARCHAR(100)` | NOT NULL, INDEX | Standardized crop name (e.g., "Wheat", "Soyabean") |
| `variety` | `VARCHAR(100)` | NOT NULL | Crop variety (e.g., "Lokwan", "Yellow") |
| `market` | `VARCHAR(150)` | NOT NULL, INDEX | Mandi / market yard name |
| `district` | `VARCHAR(100)` | NOT NULL | District name |
| `state` | `VARCHAR(100)` | NOT NULL, INDEX | State name (e.g., "Madhya Pradesh") |
| `arrival_date` | `DATE` | NOT NULL, INDEX | Trading / arrival date |
| `min_price` | `NUMERIC(10, 2)` | NOT NULL | Minimum price in ₹ / quintal |
| `max_price` | `NUMERIC(10, 2)` | NOT NULL | Maximum price in ₹ / quintal |
| `modal_price` | `NUMERIC(10, 2)` | NOT NULL | Benchmark modal price in ₹ / quintal |
| `raw_payload` | `JSONB` | NULLABLE | Full unparsed upstream payload for auditability |
| `fetched_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `now()` | Cache synchronization timestamp |
| `created_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `now()` | Record creation timestamp |
| `updated_at` | `TIMESTAMPTZ` | NOT NULL, DEFAULT `now()` | Record update timestamp |

### 4.2 Composite Natural Uniqueness Constraint
Because data.gov.in AGMARKNET records lack a globally unique identifier across releases, uniqueness is guaranteed by the composite business key:
```sql
CONSTRAINT uq_mandi_prices_natural_key UNIQUE (commodity, variety, market, arrival_date, source)
```
Upserts are executed atomically via PostgreSQL:
```sql
INSERT INTO mandi_prices (...) VALUES (...)
ON CONFLICT (commodity, variety, market, arrival_date, source)
DO UPDATE SET
    min_price = EXCLUDED.min_price,
    max_price = EXCLUDED.max_price,
    modal_price = EXCLUDED.modal_price,
    raw_payload = EXCLUDED.raw_payload,
    fetched_at = EXCLUDED.fetched_at,
    updated_at = now()
```

---

## 5. Strict Normalization & Guardrails

The normalizer (`backend/modules/prices/normalizer.py`) enforces strict agricultural and monetary integrity:
1. **No Silent Zero-Coercion**:
   - Zero, negative, missing, or sentinel values (`N/A`, `NR`, `--`) are rejected.
   - If `modal_price` is missing or invalid, the record is dropped; it is never coerced to ₹0.00/quintal.
2. **Inverted Price Auto-Correction**:
   - If an upstream Mandi operator accidentally enters `min_price > max_price`, the values are swapped.
   - If `modal_price` falls outside `[min_price, max_price]`, it is clamped to the boundary.
3. **Robust Date Parsing**:
   - Handles `DD/MM/YYYY`, `YYYY-MM-DD`, `DD-MM-YYYY`, and standard ISO formats.
4. **Text Cleaning**:
   - Strips excess whitespace, normalizes inconsistent title casing (e.g., `"WHEAT"` -> `"Wheat"`).

---

## 6. Telemetry & Observable Synchronization

The synchronization worker (`backend/modules/prices/sync.py`) collects and emits structured telemetry events:

```json
{
  "event": "mandi_prices.sync_completed",
  "status": "success",
  "provider": "agmarknet",
  "duration_ms": 1420.5,
  "records_fetched": 150,
  "records_persisted": 148,
  "records_skipped": 2,
  "errors": 0,
  "error_sample": null,
  "timestamp": "2026-09-10T02:00:00Z"
}
```

### CLI Execution
Sync can be executed as a scheduled cron job or manually:
```bash
python -m modules.prices.sync --commodity Wheat --state "Madhya Pradesh" --limit 500
```

---

## 7. HTTP API Reference

### 7.1 GET `/v1/prices`
Query mandi price records with filtering, pagination, and freshness metadata.

**Query Parameters:**
- `commodity` (string, optional): Filter by crop name (e.g., `Wheat`, `Mustard`).
- `market` (string, optional): Filter by Mandi market name.
- `state` (string, optional): Filter by state name.
- `district` (string, optional): Filter by district name.
- `arrival_date` (date string `YYYY-MM-DD`, optional): Specific arrival date.
- `page` (int, default: 1): Page number (>= 1).
- `page_size` (int, default: 20, max: 100): Records per page.

**Response (HTTP 200 OK):**
```json
{
  "prices": [
    {
      "id": "c7a8b9e1-2345-6789-abcd-ef0123456789",
      "commodity": "Wheat",
      "variety": "Lokwan",
      "market": "Rajgarh Mandi",
      "district": "Rajgarh",
      "state": "Madhya Pradesh",
      "arrival_date": "2026-09-09",
      "min_price": 2275.00,
      "max_price": 2450.00,
      "modal_price": 2360.00,
      "source": "AGMARKNET",
      "fetched_at": "2026-09-10T02:00:00Z"
    }
  ],
  "total_count": 1,
  "page": 1,
  "page_size": 20,
  "source": "AGMARKNET",
  "delivery_status": "CACHE_HIT",
  "freshness": "RECENT_CACHE",
  "fetched_at": "2026-09-10T02:00:00Z"
}
```

### 7.2 GET `/v1/prices/sync-status`
Returns metadata describing the most recent synchronization run.

**Response (HTTP 200 OK):**
```json
{
  "status": "success",
  "provider": "agmarknet",
  "last_sync_at": "2026-09-10T02:00:00Z",
  "duration_ms": 1420.5,
  "records_fetched": 150,
  "records_persisted": 148,
  "records_skipped": 2,
  "errors": 0,
  "error_sample": null
}
```

---

## 8. Configuration & Environment Variables

| Variable | Type | Default | Description |
|---|---|---|---|
| `PRICE_PROVIDER` | `str` | `"seed"` | Provider switch: `"agmarknet"`, `"seed"`, or `"mock"`. **Never auto-switches on key presence.** |
| `AGMARKNET_API_KEY` | `str` | `""` | Official API key from data.gov.in. Required if `PRICE_PROVIDER="agmarknet"`. |
| `AGMARKNET_BASE_URL` | `str` | `https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070` | Canonical endpoint for daily arrivals. |
| `AGMARKNET_TIMEOUT_SECONDS` | `float` | `10.0` | HTTP request timeout. |
| `AGMARKNET_MAX_RETRIES` | `int` | `3` | Exponential backoff retry limit for 5xx/network errors. |
| `PRICE_CACHE_TTL_HOURS` | `int` | `6` | Hours before cached prices transition to `STALE_CACHE`. |

---

## 9. Security & Key Masking

1. **URL Sanitization**: All loggers, exceptions, and audit trails mask `api-key` query parameters:
   - Original: `https://api.data.gov.in/resource/...?api-key=secret_12345&format=json`
   - Sanitized: `https://api.data.gov.in/resource/...?api-key=***&format=json`
2. **Production Startup Guard**: If `PRICE_PROVIDER="agmarknet"` and `ENVIRONMENT="production"`, `Settings.production_checks()` halts startup if `AGMARKNET_API_KEY` is missing or placeholder.
