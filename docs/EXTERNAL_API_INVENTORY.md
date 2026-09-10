# KisanQueue — External API Inventory & Integration Architecture

This document establishes the verified inventory of all external APIs, government platforms, mapping services, weather providers, telecommunications gateways, and identity verification mechanisms evaluated for KisanQueue.

---

## 1. Master API Inventory Catalog

| Service Name | Category | Production Status | Cost & Free Tier | Authentication | Primary Endpoint / Base URL | Rate Limits & Restrictions | Fallback Strategy in KisanQueue | Documentation Link |
|---|---|---|---|---|---|---|---|---|
| **Data.gov.in AGMARKNET** | Agriculture & Prices | Ready with Configuration (Pending External Credential Verification) | Free (API key required) | API Key via query param (`api-key`) | `https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070` | 10,000 req/day per key; 100 req/min | PostgreSQL `mandi_prices` DB Cache (TTL 6h) + Fallback | [Data.gov.in AGMARKNET API](https://www.data.gov.in/resource/current-daily-price-various-commodities-various-markets-mandi) |
| **CACP / MoA&FW MSP Gazette** | Agriculture & Prices | Seeded / Static | Free (Public Domain Gazette) | None (Static publication) | Ministry Gazette Notifications / DAC&FW | Published bi-annually per crop season (Kharif / Rabi) | Versioned database table (`msp_rates`) populated via Alembic seed scripts | [CACP Price Policy](https://cacp.dacnet.nic.in/) |
| **MP e-Uparjan** | Procurement | Requires Approval | Free (Government Internal) | Mutual TLS / NIC OAuth / IP Whitelist | `https://mpeuparjan.nic.in/` | Closed NIC intranet; strictly requires State Dept MoU & API approval | Offline CSV/JSON batch upload by Mandi Secretary | [MP e-Uparjan Portal](https://mpeuparjan.nic.in/) |
| **Haryana e-Kharid** | Procurement | Requires Approval | Free (Government Internal) | NIC API Gateway Token | `https://ekharid.haryana.gov.in/` | Closed state portal; restricted to authorized procurement agencies | Scheduled manual sync via administrative export/import | [Haryana eKharid](https://ekharid.haryana.gov.in/) |
| **Punjab Anaaj Kharid** | Procurement | Requires Approval | Free (Government Internal) | Mandi Board VPN / NIC Auth | `https://anaajkharid.in/` | Closed state system; no public REST API access | Mandi-level tally reconciliation reports (PDF/CSV) | [Punjab Anaaj Kharid](https://anaajkharid.in/) |
| **OpenStreetMap / Nominatim** | Geocoding | Free / Open Source | Free (Donation-supported) | Custom `User-Agent` header (mandatory) | `https://nominatim.openstreetmap.org/search` | 1 request per second; strictly prohibits bulk scraping | Client-side fuzzy search on local Mandi/Tehsil seed cache | [Nominatim Usage Policy](https://operations.osmfoundation.org/policies/nominatim/) |
| **OSRM (Public Demo)** | Routing & ETA | Development Only | Free (Demo server) | None | `https://router.project-osrm.org/table/v1/driving/` | Strictly throttled; not permitted for production workloads | Haversine formula distance approximation (`backend/modules/eta/`) | [OSRM Project](http://project-osrm.org/docs/v5.24.0/api/) |
| **Self-Hosted OSRM** | Routing & ETA | Production-ready (Self-hosted) | Compute cost only (~$10-20/mo VPS) | Internal VPC / None | `http://osrm-backend:5000/table/v1/driving/` | Unlimited (constrained only by server CPU/RAM) | Haversine formula calculation with road curvature factor (1.25x) | [OSRM Backend Docker](https://hub.docker.com/r/osrm/osrm-backend/) |
| **MapmyIndia / Mappls** | Indian Geospatial | Production-ready (Freemium) | 10,000 calls/month free; paid tiers above | OAuth 2.0 Bearer Token (Client ID & Secret) | `https://apis.mappls.com/advancedmaps/v1/` | Free tier limits; best-in-class rural Indian village settlement data | OpenStreetMap / Nominatim -> Haversine fallback | [Mappls Developer Portal](https://about.mappls.com/api/) |
| **Google Maps Platform** | Geocoding & Distance | Production-ready (Commercial) | $200 free credit monthly (~40k req); $5/1,000 req | API Key (`key=...`) | `https://maps.googleapis.com/maps/api/distancematrix/json` | Billed per request; quota management in Google Cloud Console | Mappls / Self-Hosted OSRM | [Google Distance Matrix API](https://developers.google.com/maps/documentation/distance-matrix) |
| **Open-Meteo** | Weather | Production-ready (Free) | Free up to 10,000 daily calls; commercial free | None (No API key needed) | `https://api.open-meteo.com/v1/forecast` | 10,000 req/day; Hourly rainfall, temp, weather codes | 24-hour localized forecast cache; safe default sunny fallback | [Open-Meteo Documentation](https://open-meteo.com/en/docs) |
| **IMD Mausam (Agromet)** | Weather | Production-ready (Public Domain) | Free (Public RSS / Bulletin) | None (Public bulletins) | `https://mausam.imd.gov.in/` | Dynamic REST API restricted; District Agro-Meteorological Advisories via HTML/RSS | Open-Meteo API | [IMD Mausam](https://mausam.imd.gov.in/) |
| **Meta WhatsApp Cloud API** | Notifications & Bot | Production-ready (Commercial) | 1,000 free service convs/mo; template msgs billed per Meta rate card | System User Permanent Access Token | `https://graph.facebook.com/v21.0/{phone_number_id}/messages` | 80 messages/sec (standard tier); outbound requires approved templates | Fallback to Indian DLT SMS Gateway | [WhatsApp Cloud API Documentation](https://developers.facebook.com/docs/whatsapp/cloud-api) |
| **MSG91** | Indian DLT SMS | Production-ready (Commercial) | ~INR 0.15 - 0.25 per SMS; Pay-as-you-go | `authkey` header | `https://control.msg91.com/api/v5/flow/` | Governed by TRAI DLT registration (Header + Template ID) | In-app notification / Web push notification | [MSG91 API Docs](https://docs.msg91.com/) |
| **Exotel** | Indian DLT SMS & IVR | Production-ready (Commercial) | Usage-based telephony & SMS pricing | HTTP Basic Auth (`api_key:api_token`) | `https://api.exotel.com/v1/Accounts/{AccountSid}/` | Requires DLT Entity & Header registration | MSG91 fallback | [Exotel Developer API](https://developer.exotel.com/) |
| **MeriPehchan (Jan Parichay)** | Identity SSO | Requires Approval | Free for government-recognized services | OAuth 2.0 / OpenID Connect (OIDC) | `https://janparichay.meripehchan.gov.in/` | Restricted to authorized public services & citizen utilities | Mobile OTP verification (`backend/modules/auth/`) | [MeriPehchan Portal](https://meripehchan.gov.in/) |
| **DigiLocker API** | Identity & Documents | Requires Approval | Free (Government / Partner Onboarding) | OAuth 2.0 + HMAC Signature | `https://digilocker.meripehchan.gov.in/public/oauth2/1/` | Requires formal enterprise/organization empanelment | Self-declaration of Land Records / Khasra-Khatauni numbers | [DigiLocker Developer Docs](https://partners.digitallocker.gov.in/) |
| **UIDAI Aadhaar Auth API** | Identity | Strictly Restricted | Billed per AUA/KUA contract | Digital Signature Certificate (DSC) + XML | Direct UIDAI CIDR | Strictly restricted by Aadhaar Act 2016 to registered AUAs/KUAs | Standard Mobile OTP authentication via Indian SMS | [UIDAI Technical Specifications](https://uidai.gov.in/ecosystem/authentication-ecosystem.html) |

---

## 2. Category Deep-Dives & Implementation Roadmaps

### 2.1 Agriculture & Mandi Prices (AGMARKNET & MSP)

#### Data.gov.in AGMARKNET Real-Time Commodity Prices
- **Dataset Resource ID**: `9ef84268-d588-465a-a308-a864a43d0070`
- **Data Payload**: Real-time mandi arrivals reporting:
  - `state`, `district`, `market` (Mandi name)
  - `commodity`, `variety`, `arrival_date`
  - `min_price`, `max_price`, `modal_price` (in ₹ per Quintal)
- **Integration Architecture**:
  1. Handled by `MandiPriceService` and `AgmarknetClient` (`backend/modules/prices/`).
  2. Data is normalized (clean dates, title case, strict price validation without zero-coercion) and stored in `mandi_prices` table in PostgreSQL.
  3. Deduplication enforced by composite natural key `(commodity, variety, market, arrival_date, source)` using atomic `ON CONFLICT DO UPDATE`.
  4. Decoupled provenance (`source: AGMARKNET`) from transport delivery (`LIVE_API`, `CACHE_HIT`, `FALLBACK`, `DEMO`).
  5. Decoupled data vintage (`arrival_date`) from cache recency (`fetched_at`).
  6. Observable sync telemetry (`PriceSyncSummary`) emitted on manual/scheduled execution.
- **KisanQueue Resilience**: If `data.gov.in` is unresponsive, rate-limited, or unauthorized, the backend serves cached records, sets `delivery_status="FALLBACK"`, and flags freshness as `RECENT_CACHE` (<= 6h) or `STALE_CACHE` (> 6h).
- **Subsystem Reference**: See [docs/PRICE_SYSTEM.md](file:///docs/PRICE_SYSTEM.md) for full architectural documentation.

#### Minimum Support Price (MSP) Gazette
- **Nature**: Published by the Central Government on recommendation of the CACP (Commission for Agricultural Costs and Prices) twice a year:
  - Kharif Marketing Season (Paddy, Maize, Bajra, Cotton, Soybean, etc.)
  - Rabi Marketing Season (Wheat, Mustard, Gram, Barley, etc.)
- **Implementation**: Maintained as an immutable relational table `msp_rates (id, crop_type, variety, season, marketing_year, msp_per_quintal, gazette_ref)`. No real-time external API is needed or advisable for statutory MSP figures.

#### State Procurement Portals (e-Uparjan, e-Kharid, Anaaj Kharid)
- **Status**: **REQUIRES GOVERNMENT APPROVAL / NOT PUBLICLY ACCESSIBLE**.
- **Security & Access Boundary**:
  - These systems operate within the National Informatics Centre (NIC) state data centres behind firewalls and VPNs.
  - No public REST API or OpenAPI spec is made available to general developers.
  - Direct machine-to-machine integration requires an official Memorandum of Understanding (MoU) with the State Food & Civil Supplies Department and State Agricultural Marketing Boards (Mandi Boards).
- **KisanQueue Integration Strategy**:
  - **Phase 1 (Current / SIH Baseline)**: Provide authenticated Mandi Officers with a standardized CSV/Excel ingestion tool (`POST /v1/procurement/batch-import`) conforming to state procurement schemas (Farmer Registration No., Land Record ID, Slot Allotted).
  - **Phase 2 (Pilot / MoU)**: Secure API gateway credentials using mTLS and IP whitelisting to push verified gate check-in and weighment receipts into the state portal.

---

### 2.2 Location, Routing & Distance Engines

| Provider | Pros | Cons | Recommended Stage |
|---|---|---|---|
| **Nominatim (OpenStreetMap)** | Free, open-source, zero API cost | 1 req/sec strict rate limit, prohibits automated bulk geocoding | Development & Mandi geocoding seeding |
| **OSRM (Self-Hosted)** | Zero variable costs, high throughput (1,000+ matrix calculations/sec), no third-party data leaks | Requires hosting memory (~4GB RAM for India map extract) | **Production Target (Core ETA Engine)** |
| **MapmyIndia / Mappls** | Unrivaled accuracy for Indian rural villages, panchayats, and rural feeder roads | Requires commercial license beyond free tier | Secondary geocoding verification for remote villages |
| **Google Maps Platform** | Highest global reliability, live traffic data | Expensive at scale ($5 / 1,000 distance requests) | Optional fallback for high-congestion urban mandis |

#### Production Architecture for KisanQueue ETA Engine:
1. **Mandi Locations**: Geocoded once and stored as static geospatial points (`latitude`, `longitude`) in the `procurement_centres` table.
2. **Farmer Village Locations**: Resolved at registration via Nominatim or Mappls and stored on the `farmers` profile.
3. **Distance & Travel Time**:
   - Primary: Self-hosted OSRM backend container running the India road network OSM extract (`/table/v1/driving/`).
   - Resilient Fallback: KisanQueue's built-in Haversine formula with rural road winding coefficient (1.25x average detour factor), as implemented in `backend/modules/eta/engine.py`.

---

### 2.3 Weather Monitoring (Open-Meteo & IMD)

#### Open-Meteo
- **Why Selected**: 100% open, zero-key authentication, high uptime, accurate DWD/GFS/ECMWF agricultural forecast models.
- **Data Points Used**:
  - `hourly=temperature_2m,precipitation_probability,rain,weather_code,wind_speed_10m`
  - WMO Weather interpretation codes (e.g., Code 61-65: Rain; Code 80-82: Showers; Code 95: Thunderstorm).
- **Mandi Automation Trigger**:
  - If precipitation probability > 70% or rain > 5mm/hr is forecasted within the next 4 hours for a Mandi coordinate:
    - Officer console displays an automatic weather warning alert.
    - Capacity recommendation suggests switching to covered sheds or postponing unloads of moisture-sensitive crops (Wheat/Paddy).

#### IMD Mausam & Agromet
- District Agromet Advisories (Gramin Krishi Mausam Sewa - GKMS) provide bi-weekly farming bulletins in regional languages.
- KisanQueue can ingest district bulletins as PDF/RSS summaries and attach them as advisory notes in the farmer's WhatsApp assistant feed.

---

### 2.4 Communications: WhatsApp Cloud API & Indian DLT SMS

#### Meta WhatsApp Cloud API (Graph API v21.0)
- **Onboarding Prerequisites**:
  1. Verified Meta Business Manager account.
  2. Registered phone number not currently linked to personal WhatsApp.
  3. Approved WhatsApp Business Profile (`Krishi Mitra - KisanQueue Official`).
  4. System User with `whatsapp_business_messaging` permission.
- **Message Types**:
  - **Inbound (Customer-Initiated)**: Handled by KisanQueue webhook (`POST /v1/whatsapp/webhook`). Triggers the natural language assistant (`KrishiMitraAssistant`) in Hindi, Marathi, Punjabi, or English. 24-hour customer service window opens with zero messaging charge.
  - **Outbound (Business-Initiated)**: Requires pre-approved Meta message templates for:
    - `kisanqueue_otp_verification`: One-time password for farmer onboarding.
    - `kisanqueue_pass_confirmed`: Queue pass QR link, estimated arrival time, and slot details.
    - `kisanqueue_slot_call`: Alert when farmer is top 3 in line ("Aapka number aane wala hai, kripya Gate #1 par pahuchein").
- **Webhook Verification**:
  - KisanQueue validates `hub.mode == "subscribe"` and `hub.verify_token == os.environ["WHATSAPP_VERIFY_TOKEN"]` on `GET`.
  - KisanQueue validates `X-Hub-Signature-256` HMAC-SHA256 signature using `WHATSAPP_APP_SECRET` on `POST`.

#### Indian DLT (Distributed Ledger Technology) SMS Mandate
- **Regulatory Requirement**: Under TRAI Telecom Commercial Communications Customer Preference Regulations (TCCCPR, 2018), any SMS sent in India must comply with:
  1. **Principal Entity (PE) Registration**: Company/Society registered on telecom DLT portals (Jio, Airtel, Vodafone-Idea, BSNL).
  2. **Sender ID (Header)**: 6-character header (e.g., `KISANQ`, `GOVMND`).
  3. **Content Template Registration**: Every message template must be registered with exact fixed text and variables formatted as `{#var#}`.
- **Selected Gateways**:
  - **MSG91 / Exotel**: Native Indian gateways with direct DLT template mapping, automated DLT scrubbing, and sub-second OTP delivery SLA across rural operators (BSNL, Jio, Airtel).

---

### 2.5 Farmer Identity & Authentication (Aadhaar, MeriPehchan, DigiLocker)

```
                       ┌─────────────────────────────────────────┐
                       │        Farmer Registration Flow         │
                       └───────────────────┬─────────────────────┘
                                           │
                                           ▼
                       ┌─────────────────────────────────────────┐
                       │ Primary: Mobile OTP (MSG91 / WhatsApp)  │
                       │ Verified phone number = User identity    │
                       └───────────────────┬─────────────────────┘
                                           │
                     ┌─────────────────────┴─────────────────────┐
                     │                                           │
                     ▼                                           ▼
      ┌─────────────────────────────┐             ┌─────────────────────────────┐
      │     Government / Kiosk      │             │     Farmer Self-Service     │
      │   (MeriPehchan / JanP.)     │             │    (DigiLocker Auth)        │
      ├─────────────────────────────┤             ├─────────────────────────────┤
      │ SSO for CSC / Mandi Staff   │             │ Pull verified Land Record   │
      │ Requires state onboarding   │             │ (Khasra/Khatauni) via OAuth │
      └─────────────────────────────┘             └─────────────────────────────┘
```

1. **Primary Authentication (Production Standard)**:
   - **Mobile Number + Cryptographic OTP**: Realistic, universally accessible across all Indian feature phones and smartphones. Zero friction, compliant with Digital Personal Data Protection Act (DPDP Act 2023).
2. **MeriPehchan (National Single Sign-On)**:
   - Ideal for Mandi Officers, Agricultural Extension Officers, and CSC (Common Service Centre) VLEs. Eliminates credential management by delegating auth to the Government of India SSO.
3. **DigiLocker Integration**:
   - Permits farmers to authorize KisanQueue to pull verified Land Records (Khasra/Khatauni) and PM-KISAN beneficiary IDs without uploading physical documents.
4. **UIDAI Aadhaar Authentication Status**:
   - **STRICTLY RESTRICTED**: Under Section 4 of the Aadhaar Act and Supreme Court guidelines, direct Aadhaar authentication is restricted to registered Authentication User Agencies (AUA/KUA) with licensed HSMs and strict compliance audits. KisanQueue purposefully avoids direct Aadhaar storage or API calls to protect farmer privacy and prevent legal non-compliance.

---

## 3. Configuration & Environment Blueprint

To enable live production integrations in subsequent phases, the following environment keys are prepared:

```bash
# Agriculture & Market Data
AGMARKNET_API_KEY=your_datagov_api_key_here
AGMARKNET_BASE_URL=https://api.data.gov.in/resource/9ef84268-d588-465a-a308-a864a43d0070

# Geospatial & Routing
OSRM_BACKEND_URL=http://localhost:5000
MAPMYINDIA_CLIENT_ID=your_client_id
MAPMYINDIA_CLIENT_SECRET=your_client_secret

# Weather
OPEN_METEO_BASE_URL=https://api.open-meteo.com/v1/forecast

# Telecommunications & WhatsApp
WHATSAPP_PHONE_NUMBER_ID=100609349823456
WHATSAPP_BUSINESS_ACCOUNT_ID=100609349823450
WHATSAPP_ACCESS_TOKEN=EAAB...
WHATSAPP_VERIFY_TOKEN=your_secure_verify_token
WHATSAPP_APP_SECRET=your_app_secret
SMS_GATEWAY_PROVIDER=msg91
SMS_GATEWAY_AUTH_KEY=your_msg91_auth_key
SMS_DLT_SENDER_ID=KISANQ
```

---

## 4. Architectural Summary & Chunk 2 Transition

With this inventory established and verified:
- **No speculative or dead-end APIs** are integrated.
- State procurement barriers (e-Uparjan / e-Kharid) are acknowledged with realistic CSV fallback designs.
- WhatsApp Cloud API architecture is structurally segregated from the current mock simulator, allowing seamless drop-in configuration without refactoring core bot conversational logic.
