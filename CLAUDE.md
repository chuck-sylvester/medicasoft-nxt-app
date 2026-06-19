# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This is a learning lab that simulates the MedicaSoft NXT Platform environment (FHIR repository + auth + analytics warehouse) to prepare for a Solution Engineer role. The local stack: **HAPI FHIR R4** (backed by Postgres) approximates NXT's native-FHIR repository; **Keycloak** provides OAuth2 / OIDC / SMART-on-FHIR authorization mirroring NXT's auth layer; **Synthea** generates US Core–profiled patient data; Python scripts and Jupyter notebooks handle loading, validation, and analytics.

The full implementation plan is in `docs/developer-guide.md`. That document is the authoritative reference for architecture decisions, phase-by-phase implementation steps, and learning content.

## Python environment

- Python **3.12**, **pip**, `.venv` (no uv)
- Runtime deps: `requirements.txt`; dev/optional deps: `requirements-dev.txt`
- Activate: `source .venv/bin/activate`
- Install: `pip install -r requirements.txt && pip install -r requirements-dev.txt`
- Runtime minimum: `httpx`, `python-dotenv`
- Dev/optional: `pytest`, `jupyter`, `ipykernel`, `duckdb`, `fhir.resources==7.*`, `lxml`, `hl7apy`

## Project structure

```
medicasoft-nxt-app/
├── .env                    # FHIR_BASE_URL, Keycloak client vars (gitignored)
├── requirements.txt        # Runtime dependencies
├── requirements-dev.txt    # Dev/optional dependencies
├── docker-compose.yml      # 4-service stack: HAPI + hapi-db + Keycloak + keycloak-db
├── lib/                    # Shared Python utilities
│   ├── fhir_client.py      # FHIR_BASE_URL, HEADERS, get_all(), server_validate()
│   └── smart_client.py     # SmartFhirClient — token acquisition, Bearer injection
├── scripts/                # Runnable investigation scripts
│   ├── load_synthea.py     # Posts Synthea bundles to HAPI (infra-first ordering)
│   └── validate.py         # US Core gaps + $validate + terminology census
├── notebooks/              # Jupyter notebooks (exploratory)
├── tests/                  # pytest data-quality suite
└── data/fhir/              # Synthea output (gitignored)
```

## Running the lab

**Environment config** — create `.env` at repo root before running scripts:
```
# FHIR server endpoints — python-dotenv supports ${VAR} interpolation within the file
FHIR_BASE_URL_LOCAL="http://localhost:8080/fhir"
# FHIR_BASE_URL_EXTERNAL_1="https://..."

# Active server — change the right-hand side to switch targets
FHIR_BASE_URL=${FHIR_BASE_URL_LOCAL}

# Phase 5 additions (after Keycloak realm is configured):
# KEYCLOAK_TOKEN_URL=http://localhost:8180/realms/nxt-lab/protocol/openid-connect/token
# CLIENT_ID=nxt-backend
# CLIENT_SECRET=<from Keycloak admin console>
# SMART_SCOPE=system/*.read
```

**Start Docker stack (4 services):**
```bash
docker compose up -d
docker compose ps    # all services should reach healthy/running
```

Service URLs:
- HAPI FHIR UI / REST: `http://localhost:8080/` / `http://localhost:8080/fhir`
- HAPI CapabilityStatement: `http://localhost:8080/fhir/metadata`
- HAPI SMART discovery: `http://localhost:8080/fhir/.well-known/smart-configuration`
- Keycloak Admin Console: `http://localhost:8180/` (admin / admin)
- Keycloak OIDC discovery: `http://localhost:8180/realms/nxt-lab/.well-known/openid-configuration`

**Generate Synthea data (US Core profiled):**
```bash
java -jar synthea-with-dependencies.jar \
  -p 25 -s 1234 \
  --exporter.fhir.use_us_core_ig true \
  --exporter.fhir.us_core_version 6.1.0 \
  --exporter.fhir.transaction_bundle true \
  Virginia "Fairfax"
# Synthea writes to ./output/fhir/ by default; move to the project data dir:
#   mv output/fhir/* data/fhir/
```

**Load Synthea bundles into HAPI:**
```bash
python scripts/load_synthea.py data/fhir
```

**Run validation checks:**
```bash
python scripts/validate.py
```

**Run pytest data-quality suite:**
```bash
pytest tests/ -v
pytest tests/ -v -m "not slow"    # skip $validate round-trips
```

**Start Jupyter:**
```bash
jupyter notebook notebooks/
```

## Architecture

| Component | Local stand-in | NXT equivalent |
|---|---|---|
| FHIR repository | HAPI FHIR R4 (Docker, port 8080) | MedicaSoft NXT (Couchbase) |
| Auth server | Keycloak (Docker, port 8180) | NXT SMART-on-FHIR OAuth2 layer |
| HAPI persistence | Postgres 16 — `nxt-lab-db` (internal) | — |
| Keycloak persistence | Postgres 16 — `nxt-lab-keycloak-db` (internal) | — |
| Synthetic data | Synthea (US Core 6.1.0) | Live HIE feed |
| Analytics warehouse | DuckDB (in-process) | Redshift |

**Keycloak is in the Docker stack but auth is off by default.** The `hapi-fhir` service has SMART/Spring Security environment variables commented out in `docker-compose.yml`. Uncomment them and the `keycloak` dependency in Phase 5, after the `nxt-lab` realm is configured in Keycloak.

## Key files

- **`docker-compose.yml`** — 4-service stack. Phase 5 HAPI env vars are commented out; see inline comments before editing.
- **`lib/fhir_client.py`** — shared FHIR utilities: `FHIR_BASE_URL`, `HEADERS`, `get_all()` (pagination), `server_validate()`.
- **`lib/smart_client.py`** — `SmartFhirClient`: Client Credentials token request, expiry caching, Bearer header injection.
- **`scripts/load_synthea.py`** — posts transaction bundles; infrastructure bundles load first; prints `OperationOutcome` on failure.
- **`scripts/validate.py`** — US Core Patient gap checks, server-side `$validate`, CodeSystem census (LOINC / SNOMED / RxNorm / ICD-10-CM / CVX / CPT).
- **`docs/developer-guide.md`** — full architecture, learning content, and phase-by-phase implementation plan.

## Terminology systems

Six systems surface in this lab's data or real HIE feeds: LOINC (`http://loinc.org`), SNOMED CT (`http://snomed.info/sct`), RxNorm (`http://www.nlm.nih.gov/research/umls/rxnorm`), ICD-10-CM (`http://hl7.org/fhir/sid/icd-10-cm`), CVX (`http://hl7.org/fhir/sid/cvx`), CPT (`http://www.ama-assn.org/go/cpt`). CPT is AMA-licensed and will not appear in Synthea data; extend the census to `Procedure.code` when working against real feeds.

## Docker networking note

Keycloak maps internal port 8080 to host port 8180. HAPI reaches Keycloak on the internal Docker network at `http://keycloak:8080`; Python clients and browsers reach it at `http://localhost:8180`. The HAPI Spring Security config uses `jwk-set-uri` (internal address) rather than `issuer-uri` to avoid the localhost/container-name resolution mismatch. See `docs/developer-guide.md` §5.3 for the full explanation.
