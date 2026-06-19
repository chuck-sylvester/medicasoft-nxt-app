# MedicaSoft NXT Lab
This document provides a **Developer Guide & Implementation Plan** for the **medicasoft-nxt-app** project.

## Purpose of this document

This guide is the single reference for building, understanding, and extending the NXT lab environment. It is organized so that you read the architecture and concept sections first to build a mental model, then implement in phases — each phase producing working, testable artifacts. The goal is understanding, not speed: every decision is explained so you can defend it or adapt it.

**Interview callouts** appear throughout in `> Role relevance:` blocks. They connect each technical decision to the responsibilities listed in the position description.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [How HAPI Relates to NXT](#2-how-hapi-relates-to-nxt)
3. [FHIR Concepts at the Depth This Role Requires](#3-fhir-concepts-at-the-depth-this-role-requires)
4. [Project Structure](#4-project-structure)
5. [Technology Stack Decisions](#5-technology-stack-decisions)
6. [Phase 0 — Foundation](#phase-0--foundation)
7. [Phase 1 — Data Generation and Loading](#phase-1--data-generation-and-loading)
8. [Phase 2 — REST API Exploration and Validation](#phase-2--rest-api-exploration-and-validation)
9. [Phase 3 — pytest Data-Quality Suite](#phase-3--pytest-data-quality-suite)
10. [Phase 4 — DuckDB / SQL-on-FHIR Analytics](#phase-4--duckdb--sql-on-fhir-analytics)
11. [Phase 5 — SMART-on-FHIR / OAuth2 with Keycloak](#phase-5--smart-on-fhir--oauth2-with-keycloak)
12. [Phase 6 — C-CDA to FHIR Mapper](#phase-6--c-cda-to-fhir-mapper)

---

## 1. Architecture Overview

### Local environment

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│  Host machine                                                                │
│                                                                              │
│  Python .venv                                                                │
│  ┌───────────────────────┐  ┌──────────────────────┐  ┌──────────────────┐   │
│  │  scripts/             │  │  notebooks/          │  │  tests/          │   │
│  │  load_synthea.py      │  │  Jupyter             │  │  pytest suite    │   │
│  │  validate.py          │  │  (httpx, duckdb)     │  │                  │   │
│  │  lib/smart_client.py  │  │                      │  │                  │   │
│  └───┬────────────────┬──┘  └──────┬───────────────┘  └───────┬──────────┘   │
│      │                │            │                          │              │
│      │ 1. token req   └────────────┴──────────────────────────┘              │
│      │   (port 8180)               │ 2. FHIR reqs + Bearer token             │
│      │                             │   (port 8080)                           │
│  ─ ─ ┼ ─ ─ - ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ -   │
│  Docker Compose                    │                                         │
│      │                             │                                         │
│      │              ┌──────────────▼──────────────────────────────────────┐  │
│      │              │  nxt-lab-hapi  (hapiproject/hapi:latest)            │  │
│      │   3. JWKS ──►│  FHIR R4  •  port 8080 (ext)                        │  │
│      │     fetch    │  Spring Security OAuth2 resource server             │  │
│      │     (int)    │  waits for Keycloak healthy before starting         │  │
│      │              └─────────────────────────┬───────────────────────────┘  │
│      │                                        │ JDBC (internal)              │
│      │              ┌─────────────────────────▼───────────────────────────┐  │
│      │              │  nxt-lab-db  (postgres:16-alpine)                   │  │
│      │              │  hapi database  •  port 5432 (internal only)        │  │
│      │              └─────────────────────────────────────────────────────┘  │
│      │                                                                       │
│      │  ┌─────────────────────────────────────────────────────────────────┐  │
│      └─►│  nxt-lab-keycloak  (quay.io/keycloak/keycloak:latest)           │  │
│         │  OAuth2 Authorization Server + OpenID Connect Provider          │  │
│         │  SMART-on-FHIR discovery  •  port 8180 (ext) / 8080 (int)       │  │
│         └─────────────────────────┬───────────────────────────────────────┘  │
│                                   │ JDBC (internal)                          │
│         ┌─────────────────────────▼───────────────────────────────────────┐  │
│         │  nxt-lab-keycloak-db  (postgres:16-alpine)                      │  │
│         │  keycloak database  •  port 5432 (internal only)                │  │
│         └─────────────────────────────────────────────────────────────────┘  │
│                                                                              │
│  Synthea (Java jar, run once)   data/fhir/  →  loaded by load_synthea.py     │
└──────────────────────────────────────────────────────────────────────────────┘

Flow legend:
  1.  Python → Keycloak  POST /token (Client Credentials or Auth Code exchange)
  2.  Python → HAPI      GET/POST /fhir/... with Authorization: Bearer <token>
  3.  HAPI   → Keycloak  GET /certs (JWKS — internal Docker network, port 8080)
```

### What each layer does

| Layer | Technology | What it teaches you |
|---|---|---|
| FHIR server | HAPI FHIR (Java) | The REST surface you'd triage against on NXT |
| Auth server | Keycloak | Production-realistic OAuth2 / OIDC / SMART-on-FHIR authorization |
| Persistence (HAPI) | Postgres + JPA | How FHIR JSON is persisted relationally; contrast with NXT's Couchbase |
| Persistence (Keycloak) | Postgres | Realm, client, and user configuration — survives container restarts |
| Synthetic data | Synthea | US Core–profiled real-world shapes; avoids HIPAA concerns |
| Scripted access | Python + httpx | Investigation tooling: triage, mapping, terminology |
| Notebooks | Jupyter | Exploratory analysis; live documentation of findings |
| Test suite | pytest | Repeatable data-quality gate |
| Analytics | DuckDB | Reporting-consistency checks; mirrors NXT's Redshift leg |

---

## 2. How HAPI Relates to NXT

Understanding where the analogy holds and where it breaks is important for your conversations with MedicaSoft.

### Where they are equivalent (for your purposes)

- **REST surface**: both expose FHIR R4 REST — same resources, same search parameters, same `$operations`. A query that works against HAPI works against NXT.
- **CapabilityStatement**: both publish one at `/fhir/metadata`. The capability statement is the ground truth for what a server supports. Diffing two capability statements is a real troubleshooting skill.
- **US Core conformance**: both can validate against US Core IG profiles.
- **Bulk export (`$export`)**: both support it. The mechanics (kick-off request, polling, NDJSON download) are identical.

### Where they differ

| Concern | HAPI (lab) | NXT |
|---|---|---|
| Backend store | Postgres (relational) | Couchbase (document, N1QL) |
| Querying internals | SQL / JPQL | N1QL over JSON documents |
| Scaling | Single node | Distributed |
| Auth | Keycloak (OAuth2 / OIDC / SMART) — enabled in Phase 5 | SMART-on-FHIR + OAuth2 required |
| Analytics | Not built in | Feeds Redshift warehouse |

> **Role relevance:** A Solution Engineer troubleshoots the FHIR REST surface, not the internal store. Knowing *that* NXT uses Couchbase — and understanding how FHIR JSON maps to documents — is enough to ask the right questions in an escalation. You will not administer Couchbase directly.

### HAPI's persistence model: JPA, Hibernate, and JPQL

This subsection explains the "SQL / JPQL" row in the table above. Understanding it will help you interpret HAPI's behavior in the lab — particularly why some searches are fast and others are slow — and gives you a concrete contrast point for NXT's Couchbase architecture.

#### What JPA is

**JPA** (Jakarta Persistence API, formerly Java Persistence API) is a Java specification — a contract that defines how Java objects map to relational database tables. JPA itself is just an interface definition; it needs an *implementation* to do the actual work.

The core idea is **Object-Relational Mapping (ORM)**: instead of writing raw SQL, a Java developer annotates a class with `@Entity` and its fields with `@Column`, and the JPA implementation automatically handles reading and writing rows. The Java class is called an *entity*.

**Hibernate** is the JPA implementation HAPI uses. When HAPI starts up, Hibernate reads its entity class definitions, connects to Postgres, and manages all database operations on HAPI's behalf. HAPI's Java code never writes SQL directly — it calls JPA methods (`entityManager.persist()`, `entityManager.find()`, etc.) and Hibernate generates the SQL at runtime.

Spring Boot wires Hibernate into HAPI automatically via the datasource environment variables in `docker-compose.yml` (`SPRING_DATASOURCE_URL`, etc.).

#### How HAPI maps FHIR resources to Postgres tables

HAPI does not simply dump FHIR JSON into a single blob column. It uses a *split persistence* strategy:

1. **The full FHIR JSON** is stored in a version history table — every version of every resource is preserved.
2. **Indexed search parameter values** are extracted from each resource at write time and stored in separate index tables — one table per search parameter data type. This is what makes FHIR searches fast.

The key tables (prefix `hfj_` = HAPI FHIR JPA):

| Table | Purpose |
|---|---|
| `hfj_resource` | One row per resource *current version*. Stores resource type, server-assigned ID, last updated timestamp, and current version number. |
| `hfj_res_ver` | One row per *version* of every resource. Stores the complete serialized FHIR JSON as a binary blob (`res_text`). This is the actual FHIR data. |
| `hfj_spidx_string` | String search parameter index. One row per string value per resource — e.g., a Patient's family name "Smith". |
| `hfj_spidx_token` | Token search parameter index. Stores system + code pairs — e.g., a Condition's SNOMED code, a Patient's identifier. |
| `hfj_spidx_date` | Date search parameter index. Stores low/high timestamp ranges — e.g., Patient birthdate, Condition onset date. |
| `hfj_spidx_quantity` | Quantity index — e.g., Observation numeric values with units. |
| `hfj_spidx_uri` | URI index — e.g., profile URLs in `meta.profile`. |

**Why the split matters for search behavior:**

When you run `GET /fhir/Patient?family=Smith`, HAPI does not scan the JSON blobs in `hfj_res_ver`. It queries `hfj_spidx_string` where `param_name = 'family'` and the normalized value matches "Smith", gets back matching resource IDs, then fetches full JSON from `hfj_res_ver` only for those IDs. The index table has a B-tree index on the value column — the search is fast regardless of dataset size.

When a client searches on a parameter HAPI does not index, or uses an unsupported modifier, HAPI either rejects the request or falls back to a full scan. The CapabilityStatement tells you which parameters are indexed and therefore searchable.

**Lab exercise — explore the tables directly:**

After loading Synthea data in Phase 1, connect to the HAPI database:

```bash
docker exec -it nxt-lab-db psql -U admin -d hapi
```

Useful queries inside `psql`:

```sql
-- What resource types are loaded and how many of each?
SELECT res_type, COUNT(*) FROM hfj_resource GROUP BY res_type ORDER BY count DESC;

-- What string search parameter values exist for Patient?
SELECT param_name, sp_value_normalized, COUNT(*)
FROM hfj_spidx_string WHERE res_type = 'Patient'
GROUP BY param_name, sp_value_normalized
ORDER BY param_name, count DESC LIMIT 20;

-- What token values (system + code) exist for Condition?
SELECT param_name, sp_system, sp_value, COUNT(*)
FROM hfj_spidx_token WHERE res_type = 'Condition'
GROUP BY param_name, sp_system, sp_value
ORDER BY count DESC LIMIT 20;

-- Inspect the raw FHIR JSON for one Patient
SELECT convert_from(res_text, 'UTF8')
FROM hfj_res_ver WHERE res_type = 'Patient' LIMIT 1;
```

What you see in `hfj_spidx_token` for Conditions is the same CodeSystem data your `validate.py` terminology census retrieves via REST — just the raw source from a different angle. Cross-referencing the two views is a useful exercise for understanding what the FHIR layer abstracts away.

#### What JPQL is

**JPQL** (Jakarta Persistence Query Language) is JPA's query language. It is syntactically similar to SQL but operates on *Java entity class names and field names* rather than database table and column names.

A direct SQL query against HAPI's schema:

```sql
SELECT res_id, res_type, res_updated
FROM hfj_resource
WHERE res_type = 'Patient'
ORDER BY res_updated DESC;
```

The equivalent JPQL (as HAPI's Java code expresses it):

```jpql
SELECT r FROM ResourceTable r
WHERE r.resourceType = :resourceType
ORDER BY r.updated DESC
```

`ResourceTable` is HAPI's Java entity class name; `resourceType` and `updated` are Java field names on that class. Hibernate translates this JPQL to the SQL above at runtime, substituting actual table and column names from the entity's annotations. The `:resourceType` is a named bind parameter — Hibernate substitutes the actual value safely, preventing SQL injection.

**Why this matters without writing any Java:**

- When HAPI logs a slow query or an error, it may log the JPQL or the Hibernate-generated SQL. Recognizing which is which helps you read the log.
- HAPI's search behavior maps to relational semantics — case sensitivity (driven by Postgres collation), ordering, and null handling are all relational concepts surfaced through the JPA layer. Knowing this tells you where to look when search results are surprising.
- If you escalate a HAPI performance issue, the engineering team will describe it in JPA/Hibernate terms. Knowing the vocabulary lets you participate in that conversation rather than just relay messages.

You will not write JPQL in this project. Its relevance is diagnostic and vocabulary-building.

#### The Couchbase / N1QL contrast (NXT)

NXT stores FHIR resources as JSON documents in Couchbase rather than in a relational schema. Couchbase is a distributed document database — each FHIR resource is a JSON document stored by key, with secondary indexes defined over fields within the document.

**N1QL** (Non-First Normal Form Query Language) is Couchbase's query language. It uses SQL syntax (`SELECT`, `FROM`, `WHERE`, `GROUP BY`) but operates on JSON documents. Navigating into a JSON array uses Couchbase-specific syntax:

```n1ql
SELECT meta().id, p.name, p.birthDate
FROM `fhir-bucket` p
WHERE p.resourceType = "Patient"
AND ANY n IN p.name SATISFIES n.family = "Smith" END;
```

The `ANY n IN p.name SATISFIES ... END` construct searches inside a JSON array — functionally equivalent to what HAPI does with `hfj_spidx_string`. Both approaches solve the same problem (fast search inside nested structures) with different tools.

**Side-by-side comparison:**

| | HAPI + Postgres | NXT + Couchbase |
|---|---|---|
| Storage shape | Relational rows + JSON blob | JSON documents |
| Search mechanism | Pre-extracted index tables (`hfj_spidx_*`) | N1QL with array/sub-document indexes |
| Query language | JPQL → SQL (Hibernate) | N1QL |
| Scaling model | Single-node in the lab | Distributed, horizontally scalable |
| Full document retrieval | Fetch blob from `hfj_res_ver` | Fetch document by key |

> **Role relevance:** A likely interview question: *"How does NXT store FHIR resources internally, and how does that differ from a JPA-based server like HAPI?"* The answer: NXT uses Couchbase JSON documents queried via N1QL, while HAPI uses Postgres with JPA/Hibernate extracting search parameter values into dedicated index tables at write time. The FHIR REST surface is identical — the persistence and query mechanics differ. Knowing this lets you ask the right escalation question: "Is this a missing N1QL index on the Couchbase side?" rather than guessing at the symptom level.

---

## 3. FHIR Concepts at the Depth This Role Requires

This section targets the gap between "knows FHIR basics" and "can troubleshoot a live HIE feed." Read it before writing code; refer back to it during implementation.

### 3.1 The CapabilityStatement as a diagnostic tool

Every FHIR server publishes a CapabilityStatement at `GET /fhir/metadata`. It declares:

- Which resource types are supported
- Which search parameters are supported on each type
- Which interactions are supported (`read`, `search-type`, `create`, etc.)
- Which `$operations` are implemented
- Which IGs are supported (including US Core version)

The recurring customer problem: a customer queries `Observation?component-code=...` and gets no results. The CapabilityStatement shows whether `component-code` is even a supported search parameter on that server. If it isn't listed, the server silently ignores the parameter and returns all observations — a confusing and hard-to-spot bug.

**Practice:** read HAPI's CapabilityStatement in full. Identify which search parameters exist on `Patient`, `Condition`, and `Observation`. Note that some parameters are defined in the base spec and some are US Core additions.

### 3.2 Search semantics that matter most

**`_include` and `_revinclude`**

`_include=Condition:patient` tells the server: for every Condition in the result set, also return the Patient it references. The response is a Bundle with both resource types mixed together — your code must separate them by `resourceType`.

`_revinclude=Observation:patient` is the reverse: starting from Patients, return Observations that point back to them.

The common failure mode: a customer's integration expects included resources in a specific order or key. They're not guaranteed to be — they're entries in a flat Bundle.

**Chained parameters**

`Observation?patient.name=Smith` traverses a reference at search time: find Observations whose referenced Patient has name Smith. This is evaluated server-side; the server must support the chain — not all do. NXT's capability statement will tell you.

**`_has` (reverse chaining)**

`Patient?_has:Observation:patient:code=http://loinc.org|8867-4` means: return Patients who *have* an Observation pointing back at them with that code. Useful for population queries. Less commonly supported than `_include`.

**Modifier: `:missing`**

`Condition?onset-date:missing=true` finds Conditions with no onset date. Essential for data-quality investigations.

**`_count` and paging**

The server returns a Bundle with `link` entries: `self`, `next`, `prev`. Your `get_all()` helper must follow `next` links until they stop appearing. Forgetting this is a classic bug — you think you checked all resources but only saw page one.

> **Role relevance:** The position description says "investigate issues, validate integrations." Most of those investigations are search-parameter problems. Being able to write and explain a chained `_revinclude` query with `:missing` modifiers is directly testable in an interview.

### 3.3 US Core profiling mechanics

A FHIR profile is a StructureDefinition that constrains a base resource. US Core 6.1.0 profiles say: *if you claim conformance to `us-core-patient`, your Patient resources MUST have:*

- At least one `identifier` with a system + value
- At least one `name` with a `family` or `given` element
- `gender` (required, not just must-support)
- `birthDate` (must-support)
- The `us-core-race` extension
- The `us-core-ethnicity` extension
- The `us-core-birthsex` extension (or `us-core-sex-for-clinical-use` in 6.1.0)

**Must Support vs. Required**: "Must Support" means: if your system has the data, you must send it and receiving systems must be able to receive it. It is *not* the same as required. Required elements must always be present. This distinction is a common customer misconception.

**Profile validation server-side**: sending `POST /fhir/Patient/$validate` with a resource and the header `profile=http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient` validates against the profile, not just base R4. This requires the US Core IG package to be loaded into HAPI (see README for the `application.yaml` overlay).

**Extension structure**: extensions in FHIR JSON live in the `extension` array on the resource. Each entry has a `url` (the defining StructureDefinition) and a `value[x]` element. The `us-core-race` extension is a complex extension — it contains nested `extension` entries with `ombCategory` (the coded value) and `text`. Your gap-check code needs to navigate this nested structure, not just look for the top-level URL.

### 3.4 Terminology: the six systems you need to know

| System | FHIR URI | Governs | Common problem |
|---|---|---|---|
| LOINC | `http://loinc.org` | Lab observations, vital signs, documents | Codes used for wrong purpose (a panel code where a component code is expected) |
| SNOMED CT | `http://snomed.info/sct` | Clinical findings, procedures, body sites | Licensing variation; international vs. US edition codes |
| RxNorm | `http://www.nlm.nih.gov/research/umls/rxnorm` | Medications (clinical drugs, ingredients) | Source feed sends NDC; consumer expects RxNorm — different granularity |
| ICD-10-CM | `http://hl7.org/fhir/sid/icd-10-cm` | Diagnoses (billing) | ICD-10-PCS mixed in; version mismatch (ICD-10 vs ICD-11) |
| CVX | `http://hl7.org/fhir/sid/cvx` | Vaccines | Source sends NDC or proprietary codes instead |
| CPT | `http://www.ama-assn.org/go/cpt` | Outpatient procedures, physician services (billing) | Source sends SNOMED (clinical); consumer expects CPT (billing) — crosswalk is many-to-many |

**A note on CPT's place in this list.** The first five systems will surface directly in your Synthea lab data and your terminology census. CPT will not — and that absence is itself the lesson. CPT is an **AMA-licensed** vocabulary: open-source tools (Synthea, HAPI's built-in validator, public terminology servers) cannot freely distribute or validate CPT codes. Synthea generates SNOMED CT for procedures instead. As a result:

- Your `validate.py` census will never report a CPT code against Synthea data. That does not mean CPT is rare — in production HIE feeds, CPT in `Procedure.code` is extremely common because source EHRs are billing-first.
- HAPI's `$validate` will pass a `Procedure` resource that uses CPT codes without complaint, because it cannot check codes it doesn't have. This is a silent validation gap you need to be aware of when interpreting `$validate` output.
- When you extend the census to `Procedure.code` in Phase 2 and Phase 3, expect to see SNOMED in the lab and CPT in the real world.

**The SNOMED / CPT tension.** US Core prefers SNOMED CT for `Procedure.code`. Production systems often send CPT because their billing module generates it. A single SNOMED procedure code may map to multiple CPT codes depending on context (laterality, approach, add-on codes), making automated crosswalk unreliable. CMS publishes a General Equivalence Mapping (GEM) table, but it is approximate. This mapping gap is a recurring analytics problem: the clinical system groups procedures by SNOMED; the warehouse groups by CPT; the counts appear to differ even when the underlying data is correct.

**ICD-10-PCS vs. CPT.** These are often confused. ICD-10-PCS codes *inpatient* hospital procedures (used on the UB-04 claim form). CPT codes *outpatient and physician* services (used on the CMS-1500 form). Mixing them — sending ICD-10-PCS codes in a context that expects CPT, or vice versa — is a common feed error, especially when a health system submits both inpatient and outpatient data through the same pipeline.

The terminology census in `validate.py` counts which `system` URIs appear in `Condition.code.coding` and `Observation.code.coding`. A feed is healthy when you see the expected canonical systems. A feed has a problem when you see local codes (no URI, or a hospital-specific OID) where LOINC or SNOMED is expected. When working against real feeds — as opposed to Synthea — extend the census to also cover `Procedure.code.coding`, where CPT, SNOMED, and ICD-10-PCS may all appear and need to be distinguished.

> **Role relevance:** "Terminology and code set alignment" is named explicitly in the PD. In an interview, two scenarios demonstrate this fluency well. First: an HIE customer's Condition feed shows `<none>` as the CodeSystem for 30% of records — walk through identifying the source, determining whether it's a mapping gap or a source data problem, and proposing the fix. Second: a customer reports that their Procedure counts in Redshift don't match the FHIR API — the investigation reveals the API groups by SNOMED and the warehouse groups by CPT, with no crosswalk applied at the ingest layer. Neither number is wrong; the query definitions are measuring different things. Being able to articulate *why* the counts diverge without access to the source system's code is the skill.

### 3.5 `$operations`

Operations are FHIR's extension point for non-CRUD interactions. They use the `$` prefix.

- `$validate` — validate a resource against base spec or a profile
- `$everything` — return all resources in a patient's record as a Bundle (Patient, Conditions, Observations, MedicationRequests, etc.)
- `$export` — async bulk data export (NDJSON files, one per resource type)
- `$match` — patient matching (MPI-style probabilistic matching)

Operations can be:
- **System-level**: `POST /fhir/$export`
- **Type-level**: `POST /fhir/Patient/$match`
- **Instance-level**: `GET /fhir/Patient/{id}/$everything`

### 3.6 OperationOutcome — your first triage artifact

Every FHIR server response to a failed or partially successful operation returns an `OperationOutcome` resource. It contains a list of `issue` objects, each with:

- `severity`: `fatal` | `error` | `warning` | `information`
- `code`: machine-readable issue category (e.g., `not-found`, `invalid`, `required`)
- `diagnostics`: human-readable description of the problem
- `location`: FHIRPath expression pointing to the offending element

When `load_synthea.py` prints the server response on failure, that's an `OperationOutcome`. Reading it is the first step in any ingestion triage. The `diagnostics` field typically tells you exactly which element failed and why.

---

## 4. Project Structure

Recommended final structure. You will build toward this across phases.

```
medicasoft-nxt-app/
├── .env                        # Runtime config — FHIR_BASE, etc. (gitignored)
├── .venv/                      # Python virtual environment (gitignored)
├── requirements.txt            # Runtime dependencies
├── requirements-dev.txt        # Dev/optional: duckdb, fhir.resources, pytest, jupyter
├── docker-compose.yml          # HAPI + Postgres
├── CLAUDE.md
├── README.md
│
├── lib/                        # Shared Python utilities
│   ├── __init__.py
│   ├── fhir_client.py          # FHIR_BASE, HEADERS, get_all(), server_validate()
│   └── smart_client.py         # SmartFhirClient — token acquisition, caching, Bearer injection
│
├── scripts/                    # Runnable investigation scripts
│   ├── load_synthea.py         # (moved from root; path default fixed)
│   └── validate.py             # (moved from root)
│
├── notebooks/                  # Jupyter notebooks — exploratory work
│   ├── 01_rest_exploration.ipynb
│   ├── 02_us_core_validation.ipynb
│   ├── 03_terminology_census.ipynb
│   ├── 04_analytics_duckdb.ipynb
│   └── 05_smart_auth.ipynb     # OAuth2 / SMART token flow, JWT anatomy, scope enforcement
│
├── tests/                      # pytest data-quality suite
│   ├── conftest.py             # Shared fixtures (httpx client, FHIR_BASE)
│   ├── test_us_core.py         # US Core element/extension checks
│   └── test_terminology.py     # CodeSystem census assertions
│
├── data/                       # Synthea FHIR output (gitignored)
│   └── fhir/
│
└── docs/
    └── developer-guide.md      # This document
```

**Why this structure?**

- `lib/` prevents copy-pasting `get_all()` and `FHIR_BASE` into every script and notebook. All FHIR access goes through one place.
- `scripts/` vs `notebooks/` is a deliberate split: scripts are for repeatable, commandline-invocable operations; notebooks are for exploratory, interactive work that produces visual output and prose.
- `tests/` is separate from `scripts/` because pytest has its own discovery conventions and the test suite has a different lifecycle (run on demand as a gate) from investigation scripts (run ad hoc).
- `data/` is gitignored because Synthea output is large and reproducible from a seed.

---

## 5. Technology Stack Decisions

### Python 3.12 + pip + `.venv`

The project uses pip (not uv) for package management. Before implementing any phase, establish:

1. A `.venv` at the repo root: `python3.12 -m venv .venv`
2. `requirements.txt` for runtime deps (httpx, python-dotenv)
3. `requirements-dev.txt` for dev/optional deps (pytest, jupyter, duckdb, fhir.resources)

### `python-dotenv` + `.env`

Rather than exporting `FHIR_BASE` as a shell variable before every script run, load it from `.env` at the start of each script and notebook. The `.env` file is already gitignored. The pattern: in `lib/fhir_client.py`, call `load_dotenv()` at import time so every consumer gets it automatically.

A `.env` file also makes it trivial to switch between local HAPI and a remote staging endpoint without changing code — exactly how you'd work against a customer's environment.

### `httpx` (sync, not async)

Both existing scripts use synchronous httpx. Keep it. The reasons:

- `load_synthea.py` is intentionally sequential: you want to see each OperationOutcome before posting the next bundle.
- `validate.py` is a serial investigation: the census runs after all patients are loaded.
- Async adds complexity (`async`/`await`, event loops in notebooks) with no throughput benefit here.

If you later need to post many bundles in parallel (large data loads), async httpx is a natural extension. But don't add it before you need it.

### `fhir.resources` — when to use it

As discussed, use it selectively:

| Scenario | Use `fhir.resources`? |
|---|---|
| Reading FHIR JSON from the API and checking fields | No — raw dicts are faster to write |
| Constructing a FHIR resource to POST (e.g., a Parameters resource for `$validate`) | Yes — catches structure errors before the round-trip |
| pytest assertions on resource structure | Yes — `model_validate()` is a clean assertion |
| DuckDB analytics | No — DuckDB works directly on JSON |

Pin the version: `fhir.resources==7.*` for R4. The library separates R4 (`fhir.resources.R4`) from R4B (`fhir.resources.R4B`) — always import from the R4 namespace.

### DuckDB

DuckDB is an in-process analytical SQL engine. No server, no setup — just `import duckdb`. It reads FHIR JSON directly via `read_json_auto()` and supports lateral unnesting of FHIR's nested arrays. The SQL you write transfers nearly verbatim to Redshift or Snowflake. DuckDB's UNNEST syntax and Redshift's SUPER type / UNNEST differ slightly — note those differences as you go.

### Jupyter Notebooks

Notebooks run in the `.venv` kernel. Install `jupyter` in `requirements-dev.txt`, then register the kernel: `python -m ipykernel install --user --name=nxt-lab`. This ensures notebooks use the project's venv. Notebooks import from `lib/` the same way scripts do — the project root needs to be on the Python path, which you can do with a `.pth` file or a one-line `sys.path.insert` in the notebook.

---

## Phase 0 — Foundation

*Goal: a clean, reproducible Python environment with shared infrastructure before writing any FHIR code.*

### Step 0.1 — Python virtual environment

Create `.venv` using Python 3.12 explicitly. Verify you have the right interpreter before creating it (`python3.12 --version`). Activate and confirm you're using the venv Python.

### Step 0.2 — `requirements.txt` and `requirements-dev.txt`

Decide what belongs in each. Runtime (what scripts need to run): `httpx`, `python-dotenv`. Dev/optional (what you need to develop and explore): `pytest`, `jupyter`, `ipykernel`, `duckdb`, `fhir.resources==7.*`, `hl7apy` (for Phase 6), `lxml` (for Phase 6).

Think about: should a user who only wants to run `load_synthea.py` need to install duckdb? No. That's the split.

### Step 0.3 — `.env` file

Create `.env` at the repo root (it's already gitignored). Define `FHIR_BASE=http://localhost:8080/fhir`. This is the only value you need for now — you'll add auth variables in Phase 5.

### Step 0.4 — Project folder structure

Create the directories: `lib/`, `scripts/`, `notebooks/`, `tests/`, `data/fhir/`. Add `__init__.py` to `lib/`. Update `.gitignore` to exclude `data/` (Synthea output is large and reproducible).

Move `load_synthea.py` and `validate.py` from the repo root into `scripts/`. This is a refactor — after moving, verify nothing references them at root.

### Step 0.5 — `lib/fhir_client.py`

This is the most important step in Phase 0. Design a shared module that:

1. Calls `load_dotenv()` at import time so `FHIR_BASE` is always available from the environment.
2. Defines `FHIR_BASE` and `HEADERS` as module-level constants (or a simple config object).
3. Implements `get_all(client, resource_type, **params) -> list[dict]` — the pagination helper from `validate.py`, now extracted so every script can import it. Key detail: the function must clear `params` after the first request, because HAPI encodes the full cursor into the `next` link URL — re-sending the original params on subsequent requests resets the cursor.
4. Implements `server_validate(client, resource) -> dict` — posts to `/{resourceType}/$validate` and returns the OperationOutcome.

After this step, `validate.py` should import from `lib.fhir_client` rather than defining these locally.

### Step 0.6 — Verify Docker Compose

Start the stack and confirm HAPI is healthy before moving on. The key checks:

- `GET /fhir/metadata` returns 200 with a `CapabilityStatement` resource
- `GET /fhir/Patient` returns 200 with an empty Bundle (no data yet — that's expected)
- Postgres health check passes (visible in `docker compose ps`)

**Read the CapabilityStatement fully at this point.** Before loading data, understand what HAPI supports. Note which search parameters exist on `Patient`, `Condition`, and `Observation`. This sets up your expectations for Phase 2.

---

## Phase 1 — Data Generation and Loading

*Goal: US Core–profiled synthetic data in HAPI, loaded correctly, with ingestion errors triaged.*

### Step 1.1 — Download Synthea

Download the `synthea-with-dependencies.jar` from GitHub. Verify it runs: `java -jar synthea-with-dependencies.jar --help`. Note the Java version requirement (17+).

### Step 1.2 — Understand the Synthea flags

Before running, understand what each flag does:

- `-p 25` — generate 25 patients. Start with 5–10 on the first run for speed.
- `-s 1234` — random seed for reproducibility. The same seed + same flags = identical output.
- `--exporter.fhir.use_us_core_ig true` — activates the US Core IG template, which adds the race/ethnicity extensions and generates resource types that only appear with the IG on.
- `--exporter.fhir.us_core_version 6.1.0` — pins the US Core version. 6.1.0 is the current version; earlier versions have different Must Support sets.
- `--exporter.fhir.transaction_bundle true` — wraps output in `transaction` Bundles (required for `POST /fhir` ingestion). Without this flag, Synthea produces `collection` Bundles, which HAPI won't process as a transaction.

Output lands in `./output/fhir/` by default. Move or copy it to `data/fhir/`.

### Step 1.3 — Understand `load_synthea.py` before touching it

Read the script fully. Answer these questions for yourself before changing anything:

- Why are `hospitalInformation*` and `practitionerInformation*` loaded first? (Reference resolution: patient bundles contain references like `Organization/abc123`; if that Organization doesn't exist yet, the transaction fails.)
- What does `raise_for_status()` do, and when does the `HTTPStatusError` handler trigger?
- Why does the script validate that each bundle has `"type": "transaction"`?
- What is an `OperationOutcome`, and when does HAPI return one?

**The bug to fix:** The default path in `main()` is `"./synthea/output/fhir"` but Synthea writes to `./output/fhir`. Update the default to `"./data/fhir"` (consistent with the new folder structure you created in Phase 0).

### Step 1.4 — Run the loader and triage any failures

Run the loader against your generated data. On the first run, expect some failures — they are the learning. For each `FAIL` line:

1. Read the `OperationOutcome` `diagnostics` field.
2. Identify the `severity` and `code`.
3. Determine: is this a reference-ordering problem, a validation error, or a data problem?

Common first-run failures and their causes:
- Reference to a resource that doesn't exist: ordering problem (or the reference uses a UUID that Synthea generated but the server doesn't recognize).
- Required field missing: Synthea generated data that doesn't fully satisfy the profile.
- Timeout: HAPI is still warming up — increase the `httpx.Client(timeout=...)` value.

### Step 1.5 — Verify the load

After loading, confirm the data is there:

```
GET /fhir/Patient?_count=5
GET /fhir/Patient/_count=1&_summary=count   ← returns just the total
```

The `_summary=count` parameter is a useful trick for getting a fast total without fetching full resources.

> **Role relevance:** The ordering problem in Step 1.3 is representative of the most common ingestion failure in HIE integrations: a feed sends patient-level records before the organizational context (practitioners, locations) that those records reference. Being able to diagnose this from an OperationOutcome, without access to the source system's code, is exactly "data ingestion and transformation pipeline" troubleshooting.

---

## Phase 2 — REST API Exploration and Validation

*Goal: build fluency with FHIR search semantics and the validation workflow, in both script and notebook form.*

This phase runs in parallel tracks. The scripts track produces `validate.py` (refactored); the notebooks track produces exploratory notebooks that show your reasoning and findings as prose + code + output.

### Step 2.1 — Refactor `validate.py`

Now that `lib/fhir_client.py` exists, update `validate.py` to import from it. The script body should get shorter. The logic stays the same; the plumbing moves to the library.

Also update the `us_core_patient_gaps()` function. The current implementation checks for the top-level `us-core-race` extension URL but doesn't validate the extension's internal structure (the nested `ombCategory` coding). Add that check — a race extension present but with no `ombCategory` coding is still a gap.

### Step 2.2 — Notebook: REST exploration (`01_rest_exploration.ipynb`)

Create this notebook to explore HAPI's REST surface interactively. Structure it as a progressive tutorial with prose explanations and live output:

**Section A — CapabilityStatement**
- Fetch and pretty-print the CapabilityStatement
- Write a helper cell that extracts the list of supported search parameters for a given resource type
- Compare what's listed against what you'd expect from US Core 6.1.0

**Section B — Basic search patterns**
- `_count`, `_sort`, `_fields` (partial response)
- Name search: `Patient?family=Smith`
- Date range: `Patient?birthdate=ge1960-01-01`
- Combined: `Patient?family=Smith&birthdate=ge1960-01-01`

**Section C — Reference traversal**
- `Condition?_include=Condition:patient&_count=10`
- Parse the response Bundle to separate Conditions from included Patients
- `Patient?_revinclude=Observation:patient&_id=<id>` — find all observations for a patient

**Section D — Advanced patterns**
- Chained: `Observation?patient.name=Smith`
- `_has`: `Patient?_has:Condition:patient:code=http://snomed.info/sct|73211009` (diabetes)
- `Patient/{id}/$everything` — the full record pull
- `:missing` modifier: `Condition?onset-date:missing=true`

For each pattern, document: what the query does, when you'd use it in a customer investigation, and what the response structure looks like.

### Step 2.3 — Notebook: US Core validation (`02_us_core_validation.ipynb`)

**Section A — Element/extension gap analysis**
- Load all patients using `get_all()`
- Run `us_core_patient_gaps()` on each
- Produce a summary: gap type → count, gap type → list of Patient IDs
- Visualize with a simple counter (no charting library needed — just formatted output)

**Section B — Server-side `$validate`**
- Run `server_validate()` on the first 5 patients
- Parse the OperationOutcome issues by severity
- Identify patterns: are the same elements failing across multiple patients?

**Section C — Profile validation (if US Core IG is loaded)**
- Send `$validate` with the profile URL: `http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient`
- Compare base-spec validation output to profile validation output
- Note which issues are new when validating against the profile

### Step 2.4 — Notebook: terminology census (`03_terminology_census.ipynb`)

**Section A — Condition CodeSystem census**
- Load all Conditions via `get_all()`
- Walk `code.coding` array for each, counting `system` values
- Present: system URI → count, sorted descending

**Section B — Observation CodeSystem census**
- Same for Observations (`code.coding`)
- Separately, census the `interpretation.coding` and `category.coding` — these often use different systems

**Section C — Anomaly identification**
- Find resources where `system` is `None`, empty, or an unknown URI
- Find resources using a system where a different one is expected (e.g., NDC where RxNorm is expected)
- For each anomaly: print the resource ID, the offending coding, and what system you'd expect

**Section D — Cross-resource summary**
Produce a combined table: resource type → system → count. This is the artifact you'd generate in a real customer engagement to characterize their data quality.

> **Role relevance:** This notebook is a concrete deliverable. In an interview, describe it: "I built a terminology census that runs across the full resource set, identifies CodeSystem anomalies, and produces a table I can share with the customer team." That maps directly to "investigate issues, validate integrations."

---

## Phase 3 — pytest Data-Quality Suite

*Goal: convert the validate.py checks and notebook analyses into a repeatable, maintainable test suite.*

### Step 3.1 — Understand pytest's architecture for this use case

This is not a unit test suite — there's no mocking. It's an integration test suite that runs against a live HAPI instance. That design choice has implications:

- Tests require the Docker stack to be running (document this as a prerequisite in the test module's docstring)
- Tests are read-only — they GET data, they don't POST or mutate
- A test failure means a data-quality issue in the loaded dataset, not a code bug

### Step 3.2 — `tests/conftest.py`

This file contains shared pytest fixtures. The most important fixture: an `httpx.Client` scoped to the test session (one client for all tests, not one per test). This requires understanding pytest's fixture scoping (`scope="session"`).

The client should read `FHIR_BASE` from the environment (via `python-dotenv`), and the fixture should fail fast with a clear error if HAPI isn't reachable, rather than failing obscurely in every test.

A second fixture: `all_patients` — fetches all patients once at session scope using `get_all()`. Many tests need the full patient list; fetching it once avoids N network round-trips.

### Step 3.3 — `tests/test_us_core.py`

**Test 1: All patients have identifiers**

Use `pytest.mark.parametrize` with a list of `(patient_id, has_identifier)` tuples. Each patient is a separate test case — pytest will report which specific patients fail, not just a count.

The fixture that builds this list is a good use of `@pytest.fixture` — compute it once, parametrize from it.

**Test 2: All patients have the race extension**

Same pattern. Check for the `us-core-race` extension URL, and within it, at least one `ombCategory` nested extension with a non-empty `valueCoding`.

**Test 3: All patients have gender**

Simpler — just check for the `gender` key.

**Test 4: `$validate` produces no fatal or error issues on any patient**

This one is slower (N server round-trips). Consider marking it with `@pytest.mark.slow` and excluding it from the default run. You can configure pytest markers in `pyproject.toml` or `pytest.ini`.

### Step 3.4 — `tests/test_terminology.py`

**Test 1: All Condition.code codings use a recognized system**

Define a set of allowed systems (SNOMED, ICD-10-CM). Fail for any coding with a system outside that set or with no system.

**Test 2: All Observation.code codings include LOINC**

A coding on an Observation doesn't need to use *only* LOINC, but at least one coding in the array should be LOINC. Fail for any Observation with no LOINC coding in `code.coding`.

**Test 3: No MedicationRequest uses NDC where RxNorm is expected**

If you extend to Medications — NDC (`http://hl7.org/fhir/sid/ndc`) and RxNorm (`http://www.nlm.nih.gov/research/umls/rxnorm`) both code medications. A feed sending NDC where RxNorm is expected is a terminology alignment failure.

### Step 3.5 — Running the suite

`pytest tests/ -v` — verbose output showing each parametrized case.

`pytest tests/ -v -m "not slow"` — skip the `$validate` tests.

`pytest tests/test_us_core.py::test_all_patients_have_race_extension -v` — run one test.

Consider adding a `Makefile` target: `make test` that activates the venv and runs pytest. This is the "lightweight tooling" pattern the PD describes — one command to run the data-quality gate.

> **Role relevance:** "Turn validate.py into a pytest suite so you have a reusable data-quality gate" is the README's own description of what this phase produces. In an interview context: "I built a parametrized pytest suite that treats each patient as a separate test case, so when the suite runs against a customer's feed, you can see exactly which records have US Core gaps — not just a count."

---

## Phase 4 — DuckDB / SQL-on-FHIR Analytics

*Goal: flatten FHIR resources into a queryable SQL layer and demonstrate reporting-consistency investigation.*

### Step 4.1 — Understand what you're simulating

NXT's analytics architecture: the FHIR repository (Couchbase) feeds a Redshift data warehouse. The recurring customer ticket is: "the warehouse count for Condition doesn't match the API count." The cause is usually one of:

1. **Replication lag**: the warehouse is N minutes/hours behind the FHIR repository.
2. **Filter mismatch**: the warehouse query filters on a field (e.g., `status=active`) that the API query doesn't.
3. **Deduplication difference**: the API exposes all versions; the warehouse may only keep the latest.
4. **Code system mismatch**: the warehouse groups by SNOMED code; the source has ICD-10 codes.

Your local DuckDB leg lets you simulate scenarios 2–4 directly.

### Step 4.2 — Notebook: analytics (`04_analytics_duckdb.ipynb`)

**Section A — Loading FHIR JSON into DuckDB**

Fetch Conditions from the FHIR API (using `get_all()`) and load them into DuckDB. Understand `read_json_auto()` — DuckDB infers the schema from the JSON. FHIR's nested arrays (like `code.coding`) require unnesting.

Key DuckDB functions for FHIR:
- `json_extract()` / `->` operator for navigating nested JSON
- `UNNEST()` for expanding arrays (e.g., expand `code.coding` into rows)
- `list_aggregate()` for working with JSON arrays

**Section B — Reporting-consistency queries**

Write queries that a customer's BI team might run in Redshift:
- Condition count per patient
- Top 10 SNOMED codes across all Conditions
- Patients with more than 5 active Conditions
- Observations per patient per month (time series)

Then run the equivalent FHIR API query and compare the counts. Intentionally introduce a filter mismatch (e.g., the API query doesn't filter by status; the SQL query does) and show how the counts diverge.

**Section C — SQL-on-FHIR v2 ViewDefinitions**

SQL-on-FHIR v2 is an HL7 specification that defines `ViewDefinition` resources — declarative JSON documents that specify how to flatten a FHIR resource into a tabular view. Pathling and other tools implement this spec.

Write one ViewDefinition by hand for `Condition` — it specifies column names and FHIRPath expressions that extract values from the resource. Then implement it in DuckDB SQL (DuckDB doesn't natively consume ViewDefinitions, but you can translate a ViewDefinition to a DuckDB query manually). This gives you a concrete understanding of the spec before you encounter it in NXT's architecture.

**Section D — Redshift dialect notes**

Document the differences you'd encounter moving from DuckDB to Redshift:
- DuckDB: `UNNEST(code.coding)` — Redshift: `SELECT ... FROM ... CROSS JOIN UNNEST(code.coding) AS t(coding_element)`
- DuckDB: `read_json_auto()` — Redshift: SUPER type with `json_parse()`
- DuckDB: `->` operator — Redshift: `json_extract_path_text()`

This table is a useful reference when the SQL needs to run in the actual warehouse.

> **Role relevance:** Being able to reproduce a reporting-consistency discrepancy end-to-end — pull from the API, load into SQL, run the warehouse query, and find the filter that explains the count difference — is a direct demonstration of "analytics warehouse integration and reporting consistency" from the PD.

---

## Phase 5 — SMART-on-FHIR / OAuth2 with Keycloak

*Goal: stand up Keycloak as a production-realistic OAuth2 / OIDC authorization server, wire it to HAPI, and exercise the Client Credentials and Authorization Code flows that mirror what NXT exposes for system integrations and CMS Patient Access.*

---

### 5.0 Background: The Technology Stack

Read this section fully before touching any configuration. These four layers build on each other, and confusing which layer does what is the most common source of auth debugging dead-ends.

#### OAuth 2.0 — the authorization framework

OAuth 2.0 (RFC 6749) is a delegation protocol. It answers the question: *how does an application obtain permission to access a resource on behalf of a user or system, without the user handing over their credentials to the application?*

**The four roles:**

| Role | In this lab | In NXT |
|---|---|---|
| Resource Owner | A person (patient, clinician) or the system itself | The HIE customer or their patients |
| Client | Your Python app or FastAPI web app | A customer's integration engine or patient portal |
| Authorization Server | Keycloak | NXT's auth layer (SMART-compliant OAuth2 server) |
| Resource Server | HAPI FHIR | NXT's FHIR API |

**The three grant types you need to know:**

*Client Credentials* (`grant_type=client_credentials`) — no user is involved. The client authenticates directly with the auth server using a `client_id` and `client_secret`. The auth server returns an access token. This is system-to-system: an integration engine calling a FHIR API on its own behalf. This is the most SE-relevant flow.

*Authorization Code + PKCE* (`grant_type=authorization_code`) — a user is involved. The flow:
1. The client redirects the user's browser to the authorization server's login page
2. The user authenticates (username/password, MFA, etc.)
3. The authorization server redirects back to the client with a short-lived one-time `code`
4. The client exchanges the `code` for tokens (access token + optionally ID token + refresh token) in a back-channel POST — this exchange never touches the browser
5. PKCE (Proof Key for Code Exchange) prevents interception of the `code` in step 3: the client generates a random `code_verifier`, sends a hash (`code_challenge`) in step 1, and sends the original `code_verifier` in step 4; the auth server verifies they match

*Refresh Token* — not a standalone grant; it's a token issued alongside the access token in Authorization Code flow. Access tokens are short-lived (minutes to hours); the client uses the refresh token to obtain a new access token without repeating the login flow. Client Credentials does not issue refresh tokens — the client can just request a new access token at any time.

**Token endpoint vs. authorization endpoint:**

- *Authorization endpoint* — the URL the user's browser visits to log in: `GET /realms/nxt-lab/protocol/openid-connect/auth`. Only used in Authorization Code flow.
- *Token endpoint* — the URL the client POSTs to (server-to-server) to exchange credentials or codes for tokens: `POST /realms/nxt-lab/protocol/openid-connect/token`. Used in all grant types.
- *JWKS endpoint* — the URL where the auth server publishes its public keys, used by the resource server (HAPI) to verify token signatures: `GET /realms/nxt-lab/protocol/openid-connect/certs`.
- *UserInfo endpoint* — an OIDC endpoint where the client can fetch user profile claims using an access token: `GET /realms/nxt-lab/protocol/openid-connect/userinfo`. Only relevant when OIDC is in use.
- *Introspection endpoint* — an alternative to JWT validation where the resource server POSTs the token to the auth server to ask "is this token valid?". Used for opaque (non-JWT) tokens. HAPI with Keycloak uses JWT validation (JWKS), not introspection.

#### JWT — the token format

A JSON Web Token (JWT, RFC 7519) is the access token format used in this stack. A JWT is three base64url-encoded segments separated by dots:

```
<header>.<payload>.<signature>
```

**Header** — a JSON object identifying the token type and signing algorithm:
```json
{
  "alg": "RS256",
  "typ": "JWT",
  "kid": "some-key-id"
}
```
`RS256` means the token was signed with an RSA private key using SHA-256. The `kid` (Key ID) is used to look up the matching public key in the JWKS endpoint — Keycloak rotates keys periodically, and `kid` tells the resource server which key to verify with.

**Payload** — a JSON object of claims (assertions about the token and its subject):

| Claim | Name | Meaning |
|---|---|---|
| `iss` | Issuer | Who created the token: `http://localhost:8180/realms/nxt-lab` |
| `sub` | Subject | Who the token is about: a user ID (Auth Code) or client ID (Client Credentials) |
| `aud` | Audience | Who the token is intended for — must match the resource server's configured value |
| `exp` | Expiration | Unix timestamp after which the token is invalid |
| `iat` | Issued At | Unix timestamp when the token was created |
| `scope` | Scope | Space-separated list of granted OAuth2 scopes |
| `azp` | Authorized Party | The client that requested the token |
| `fhirUser` | FHIR User | (SMART/OIDC) FHIR reference to the user: `Practitioner/123` |

**Signature** — the base64url-encoded RSA signature over `<header>.<payload>`. Only Keycloak has the private key; anyone with the public key (from JWKS) can verify it.

**How HAPI validates a JWT:**
1. Decode the header and extract `kid`
2. Fetch the JWKS endpoint and find the public key matching `kid`
3. Verify the signature using the public key
4. Check `exp` — reject if expired
5. Check `iss` — reject if issuer doesn't match configured value
6. Check `aud` — reject if audience doesn't include this server
7. Check `scope` — reject if required scope is absent

Steps 5–6 are the most common misconfiguration points. In a local lab with Docker networking, the `iss` claim (set by Keycloak using its external URL) and the issuer HAPI is configured to expect (reachable from inside Docker) are often different addresses for the same server. This is covered in Step 5.3.

You can inspect any JWT without a library: split on `.`, base64url-decode the middle segment (padding with `=` as needed), and `json.loads()` the result. This is a diagnostic technique worth knowing because you'll often need to inspect a customer's token in the field without installing anything.

#### SMART-on-FHIR — the FHIR profile of OAuth 2.0

SMART-on-FHIR (currently v2, HL7 published) layers three things on top of OAuth 2.0:

**1. Discovery** — the FHIR server publishes a document at `GET /fhir/.well-known/smart-configuration` (not on Keycloak — on HAPI) that tells clients where to authenticate:
```json
{
  "issuer": "http://localhost:8180/realms/nxt-lab",
  "authorization_endpoint": "http://localhost:8180/realms/nxt-lab/protocol/openid-connect/auth",
  "token_endpoint": "http://localhost:8180/realms/nxt-lab/protocol/openid-connect/token",
  "jwks_uri": "http://localhost:8180/realms/nxt-lab/protocol/openid-connect/certs",
  "grant_types_supported": ["authorization_code", "client_credentials"],
  "scopes_supported": ["openid", "fhirUser", "offline_access", "patient/*.read", "patient/Patient.read", "user/*.read", "system/*.read", ...]
}
```
A SMART client reads this document before initiating any flow — it never hardcodes auth server URLs. This is how NXT customers would discover NXT's auth endpoints.

**2. Scopes** — SMART defines a naming convention for OAuth2 scopes that maps to FHIR resource access. The v2 pattern: `<context>/<ResourceType>.<actions>` where actions are a subset of `cruds` (create, read, update, delete, search). A `*` wildcard is valid for both `ResourceType` (any resource) and `actions` (all permissions). This table shows the patterns relevant to this role — read-focused because the SE role is investigation-heavy, not write-heavy.

| Scope | Meaning | Grant type |
|---|---|---|
| `system/*.read` | Read **any** resource type, system-wide | Client Credentials |
| `system/Patient.read` | Read **only Patient** resources, system-wide | Client Credentials |
| `user/*.read` | Read **any** resource type for patients this user can access | Authorization Code |
| `user/Condition.read` | Read **only Conditions** for patients this user can access | Authorization Code |
| `patient/*.read` | Read **any** resource type for the in-context patient only | Authorization Code |
| `patient/Patient.read` | Read **only the Patient** resource for the in-context patient | Authorization Code |
| `openid` | Request an ID token (OIDC) | Authorization Code |
| `fhirUser` | Include the `fhirUser` claim in the ID token | Authorization Code |
| `offline_access` | Request a refresh token | Authorization Code |

**`patient/*.read` vs. `patient/Patient.read`** — this distinction matters in practice. `patient/Patient.read` grants access only to the Patient demographic resource; it does not authorize reading the patient's Conditions, Observations, MedicationRequests, or any other clinical data. `patient/*.read` grants read access to all resource types scoped to the in-context patient, which is what a patient portal actually needs. CMS Patient Access implementations typically request `patient/*.read` (or an explicit list of resource types) along with `openid` and `offline_access`.

**On CRUDS write permissions** — SMART v2 supports full `c`/`u`/`d` permissions (e.g., `system/Patient.cu`, `patient/*.cruds`). Write scopes matter when troubleshooting an integration that fails to persist or update data. For read-only investigation tooling — the primary SE workflow — the `r` and `s` actions are sufficient.

The context matters: `system/` scopes are for backend systems with no user; `user/` scopes are for clinician-facing apps; `patient/` scopes are for patient-facing apps (CMS Patient Access). Client Credentials flow can only use `system/` scopes.

**3. Launch context** — SMART defines two launch patterns:

*Standalone launch* — the app initiates authentication on its own, without a host EHR system providing context. The user logs in, and the app discovers which patient to load (or asks the user). This is the most common pattern for standalone apps.

*EHR launch* — an EHR system launches the SMART app with a `launch` token that carries context (which patient, which encounter). The app exchanges this token during the auth flow to receive a `patient` value in the token response. This is how a SMART app embedded in an EHR works. The lab doesn't simulate a full EHR, so this pattern is conceptual here.

#### OpenID Connect (OIDC) — the identity layer

OpenID Connect 1.0 is a thin identity layer on top of OAuth 2.0. The difference: OAuth 2.0 answers "is this client authorized to access this resource?" — it says nothing about who the user is. OIDC answers "who is the user?" by adding:

- The `openid` scope triggers OIDC behavior
- The auth server returns an **ID token** alongside the access token
- The ID token is a JWT that identifies the user (not the authorization to access resources)

**Access token vs. ID token — the critical distinction:**

| | Access Token | ID Token |
|---|---|---|
| Purpose | Authorize access to a resource | Identify the user to the client |
| Who consumes it | The resource server (HAPI) — validates it on every request | The client app — reads it once to know who logged in |
| Should be sent to HAPI? | Yes, in `Authorization: Bearer` header | No — never send the ID token to a resource server |
| Contains | Scopes, expiry, audience | User claims: name, email, `sub`, `fhirUser` |
| Available in | Authorization Code + `openid` scope | Authorization Code + `openid` scope |
| Available in Client Credentials? | Yes | No — no user to identify |

**The `fhirUser` claim** is a SMART OIDC extension: it contains a FHIR resource reference (`Practitioner/123`, `Patient/456`) linking the logged-in user to their corresponding FHIR resource. A clinician portal uses this to know which Practitioner the user corresponds to and what data they're authorized to see.

**The UserInfo endpoint** (`GET /userinfo` with the access token as `Authorization: Bearer`) returns the same user claims as the ID token but as a plain JSON response. Useful when you need to fetch user identity after the initial token exchange.

#### Keycloak — the auth server

Keycloak is an open-source Identity and Access Management (IAM) platform. For this lab it acts as:
- An OAuth 2.0 Authorization Server (issues access tokens)
- An OpenID Connect Provider (issues ID tokens, publishes UserInfo endpoint)
- A user directory (manages test users for Authorization Code flow)

**Keycloak's data model:**

*Realm* — the top-level namespace and configuration boundary. Think of it as a tenant. Each realm has its own users, clients, roles, and keys. Create a `nxt-lab` realm for this project. The `master` realm is Keycloak's admin realm — don't use it for application configuration.

*Client* — a registered application. Each application that wants to obtain tokens must be registered as a client. Key client settings:
- **Client authentication** (`ON`/`OFF`): `ON` = confidential client (has a client secret, used for Client Credentials and back-channel Authorization Code). `OFF` = public client (no secret, used for browser-only Authorization Code + PKCE).
- **Standard flow enabled**: enables Authorization Code flow
- **Service accounts enabled**: enables Client Credentials flow (creates a service account user in Keycloak)
- **Valid redirect URIs**: where the browser is allowed to redirect after login (e.g., `http://localhost:8000/callback` for a FastAPI app)

*Client scope* — a reusable scope definition. You create Keycloak client scopes to represent SMART scopes (`system/*.read`, `patient/Patient.read`, etc.) and then assign them to clients.

*Role* — Keycloak roles can be mapped to JWT claims. In SMART, scopes are the authorization mechanism, not roles — but Keycloak roles can be used to populate the `scope` claim via protocol mappers.

*Protocol mapper* — a Keycloak configuration that shapes the token content. To include the `scope` claim as a space-separated string in the JWT (as SMART requires), you add a protocol mapper to the client. HAPI reads the `scope` claim from the JWT to enforce access control.

*Service account* — when Client Credentials is enabled on a confidential client, Keycloak creates a virtual user called the "service account user" for that client. You can assign roles and scopes to the service account, which then appear in the access token.

---

### Step 5.1 — Review `docker-compose.yml` and enable HAPI's SMART wiring

The `docker-compose.yml` already contains all four services (`hapi-fhir`, `hapi-db`, `keycloak`, `keycloak-db`). Read through the entire file before running anything. Understand each configuration decision before enabling auth.

**Key configuration decisions to understand:**

*Port mapping*: HAPI occupies host port 8080. Keycloak's container runs on internal port 8080 but is mapped to host port 8180 (`8180:8080`). This means:
- External clients (your Python scripts, browser) reach Keycloak at `http://localhost:8180`
- HAPI reaches Keycloak via Docker's internal network at `http://keycloak:8080` (the internal container port, not the host port)

*Frontend URL*: `KC_HOSTNAME_URL=http://localhost:8180` tells Keycloak what external URL to use for the `iss` claim in JWTs. The issuer will be `http://localhost:8180/realms/nxt-lab` — the address your Python client and browser can reach. Without this, Keycloak would use its internal address, which would be unreachable from outside Docker.

*Start mode*: `start-dev` is used for the lab. Production mode (`start`) requires TLS certificates. `start-dev` disables TLS requirements and enables the admin console at the root URL.

*Health check*: Keycloak is slow to start (30–90 seconds). The health check on management port 9000 at `/health/ready` (enabled by `KC_HEALTH_ENABLED=true`) prevents HAPI from trying to validate tokens before Keycloak is ready. The `start_period: 90s` gives the JVM time to initialise before health checks begin.

*HAPI Spring Security block*: The `docker-compose.yml` contains the HAPI SMART environment variables as comments. Do not uncomment them yet. They reference the `nxt-lab` Keycloak realm, which doesn't exist until Step 5.2. Enabling them before the realm exists will cause HAPI to fail on startup when it tries to fetch the JWKS.

*HAPI dependency*: The `keycloak` dependency on the `hapi-fhir` service is also commented out for the same reason — enabling it before the realm exists would cause HAPI to wait indefinitely for a Keycloak realm that isn't configured.

**What to do now:** Start the stack (`docker compose up -d`) and verify all four containers reach a healthy or running state (`docker compose ps`). Keycloak will be running but unconfigured — no realm, no clients. HAPI will start without auth enforcement. Verify HAPI is accessible at `http://localhost:8080/fhir/metadata` and Keycloak's admin console is accessible at `http://localhost:8180` before proceeding to Step 5.2.

### Step 5.2 — Create the Keycloak realm and clients

Do this through Keycloak's Admin Console at `http://localhost:8180`. Keycloak also supports a REST API and realm export/import (JSON), which is the repeatable approach — but use the console first to understand the model before scripting it.

**Create the realm:**

Create a new realm named `nxt-lab`. All subsequent configuration lives inside this realm. Note the realm's OIDC discovery URL: `http://localhost:8180/realms/nxt-lab/.well-known/openid-configuration` — this JSON document lists every endpoint and capability. Read it in full; it's the OIDC equivalent of HAPI's CapabilityStatement.

**Create Client 1: `nxt-backend` (Client Credentials / confidential)**

This client represents your Python scripts acting as a backend system integration — the same role an integration engine would play with NXT.

Settings to configure:
- Client authentication: `ON` (makes it confidential; generates a client secret)
- Standard flow: `OFF` (not doing browser login with this client)
- Service accounts: `ON` (enables Client Credentials grant)
- After saving, copy the client secret from the "Credentials" tab into your `.env` file

For SMART scopes, you have two approaches in Keycloak:
- *Client scopes approach*: create Keycloak client scopes named `system/*.read`, `system/Patient.read`, etc., assign them to the client, and add a "User Client Role" or "Hardcoded claim" protocol mapper that puts the scope string into the JWT `scope` claim
- *Realm roles approach*: create roles, assign them to the service account, add a protocol mapper that converts roles to the `scope` claim

The client scopes approach is closer to how SMART intends scopes to work. Whichever you choose, the end result must be a JWT with a `scope` claim containing the space-separated SMART scopes you granted.

**Create Client 2: `nxt-webapp` (Authorization Code + PKCE / public)** *(for the stretch steps)*

This client represents a browser-facing FastAPI app.

Settings:
- Client authentication: `OFF` (public client — no secret, uses PKCE instead)
- Standard flow: `ON`
- Service accounts: `OFF`
- Valid redirect URIs: `http://localhost:8000/callback` (your FastAPI callback route)
- Valid post logout redirect URIs: `http://localhost:8000/`
- Web origins: `http://localhost:8000` (for CORS)

**Create a test user** *(for Authorization Code flow)*

In the `nxt-lab` realm, create at least one user with a username, email, and password. This is the user who will log in via the browser in the stretch steps.

**Verify the realm configuration:**

Before wiring HAPI, confirm the realm is working by making a direct token request to Keycloak from your terminal using `curl`. You should be able to obtain an access token from the Client Credentials endpoint and decode the JWT payload manually. Verify the `iss`, `scope`, and `exp` claims look correct before involving HAPI.

### Step 5.3 — Wire HAPI to Keycloak

This step configures HAPI to validate tokens issued by Keycloak. HAPI's SMART-on-FHIR support is implemented via Spring Security's OAuth2 Resource Server. Configuration goes in the `hapi-fhir` service's environment variables in `docker-compose.yml` (or a mounted `application.yaml`).

**Key configuration:**

The most important setting is how HAPI fetches Keycloak's public keys to verify JWT signatures. There are two approaches:

*Issuer URI approach*: `spring.security.oauth2.resourceserver.jwt.issuer-uri=<keycloak-issuer>`. Spring auto-discovers the JWKS URI by fetching `{issuer-uri}/.well-known/openid-configuration`. This is cleaner but creates a Docker networking problem: the issuer URI in JWTs is `http://localhost:8180/realms/nxt-lab` (Keycloak's external URL), but HAPI runs inside Docker and can't reach `localhost:8180`.

*JWKS URI approach*: `spring.security.oauth2.resourceserver.jwt.jwk-set-uri=http://keycloak:8080/realms/nxt-lab/protocol/openid-connect/certs`. HAPI fetches keys directly from the internal Docker network address. This bypasses the external URL problem. The trade-off: you also need to configure the expected issuer separately, or HAPI may reject tokens whose `iss` doesn't match the JWKS URI's host.

**Recommended approach for the lab:** use `jwk-set-uri` pointing at `http://keycloak:8080/...` (internal Docker network) to avoid the networking mismatch. Document the issuer discrepancy — you're intentionally trading strict issuer validation for lab simplicity, but in production both addresses would resolve to the same server.

**SMART-on-FHIR publication:**

Add `hapi.fhir.smart_enabled=true` to the HAPI environment. This tells HAPI to publish `/.well-known/smart-configuration`, populated with the auth server endpoints you configure. Verify it after restarting: `GET http://localhost:8080/fhir/.well-known/smart-configuration` should return a JSON document listing Keycloak's endpoints.

**Verify protection is active:**

After restarting the stack, an unauthenticated request to HAPI should now return HTTP 401. This is the first confirmation that the wiring is correct. If you still get 200, SMART enforcement isn't enabled — check the HAPI environment variables and logs.

> **The Docker networking issuer mismatch** is a real-world problem in miniature. In production, NXT's auth server has a single DNS name reachable from both internal services and external clients. In a local lab with Docker port mapping, the internal and external addresses differ. Knowing this problem exists — and knowing to look at the `iss` claim in the JWT and compare it to what the resource server is configured to expect — is exactly the diagnostic skill you'd apply when a customer reports "401 Unauthorized" on a freshly configured integration.

### Step 5.4 — Client Credentials flow (Python, no browser)

Implement a `SmartFhirClient` class in `lib/smart_client.py`. This class is the Python embodiment of the Client Credentials flow. Design it so that:

- It reads `KEYCLOAK_TOKEN_URL`, `CLIENT_ID`, `CLIENT_SECRET`, and `SCOPE` from the environment (add these to `.env`)
- It holds the current access token and its expiry time as instance state
- It exposes a method to get a valid token: if the cached token is still valid (with a small buffer, e.g., 30 seconds before expiry), return it; otherwise request a new one
- It wraps `httpx.Client` so that all FHIR requests automatically include `Authorization: Bearer <token>`

The token request is a standard OAuth2 Client Credentials POST:
- URL: `KEYCLOAK_TOKEN_URL`
- Body (form-encoded, not JSON): `grant_type=client_credentials`, `client_id`, `client_secret`, `scope`
- Response: JSON with `access_token`, `token_type`, `expires_in`, optionally `scope`

Token expiry calculation: `expires_at = current_time + expires_in`. On each request, check `current_time < expires_at - 30`.

**Decode and inspect the token:**

After obtaining the access token, decode the payload without a library: split on `.`, take index 1, add padding (`+ '=='`), `base64.urlsafe_b64decode()`, then `json.loads()`. Print the claims. Verify:
- `iss` matches your Keycloak realm URL
- `scope` contains the scopes you requested
- `exp` is a future timestamp
- `aud` — note what audience Keycloak issued (this matters for HAPI's audience check)

**Make an authenticated FHIR request:**

Use `SmartFhirClient` to call `GET /fhir/Patient?_count=5`. This should succeed with the same result as before SMART was enabled — the only difference is the `Authorization` header. If it fails with 401, the token validation chain has a break — work through it step by step using the JWT claims you decoded.

### Step 5.5 — Scope enforcement and deliberate failure exercises

The most valuable learning in this phase comes from deliberately breaking things. Each failure teaches you exactly what HAPI checks and in what order. Work through each scenario, note the HTTP status code and response body, and document what broke.

**Exercise 1 — No token**
Make a request to HAPI with no `Authorization` header.
*Expected:* 401 Unauthorized
*What it teaches:* SMART enforcement is active

**Exercise 2 — Expired token**
Manually set `expires_in` to 1 second in the token response (or directly modify the `exp` claim if you're issuing test tokens), wait, then make a request.
*Expected:* 401 Unauthorized
*What it teaches:* HAPI checks `exp` on every request; your client must handle token refresh

**Exercise 3 — Wrong audience**
Configure HAPI's expected audience to a value that doesn't match what Keycloak issues, or request a token with a different `aud`. (In Keycloak, audience can be configured per client via the Audience mapper under Client Scopes.)
*Expected:* 401 Unauthorized
*What it teaches:* `aud` mismatch is a common misconfiguration when FHIR server address changes

**Exercise 4 — Insufficient scope**
Request a token with no scope or a scope that doesn't authorize Patient access (`scope=openid` only). Then attempt `GET /fhir/Patient`.
*Expected:* 403 Forbidden (authenticated but not authorized)
*What it teaches:* 401 vs 403 distinction — "who are you?" vs "you don't have permission"

**Exercise 5 — JWKS endpoint unreachable**
Stop the Keycloak container (`docker compose stop keycloak`) and make a FHIR request with a previously obtained token.
*Expected:* HAPI may serve cached keys for a time, then fail with 401 or 500 once the cache expires
*What it teaches:* HAPI caches JWKS keys — there's a window where requests succeed even after the auth server goes down, then a hard failure

**Exercise 6 — Tampered token**
Take a valid JWT, decode the payload, change the `scope` claim, re-encode (without re-signing), and send it.
*Expected:* 401 Unauthorized
*What it teaches:* The signature covers the entire `<header>.<payload>`; any change invalidates it — this is why JWTs can be trusted without calling the auth server on every request

Document each result in a notebook cell. This exercise set is a complete diagnostic runbook for the most common SMART authentication failures.

### Step 5.6 — Notebook: SMART client exercise (`05_smart_auth.ipynb`)

Create a notebook that tells the complete story of this phase as a narrative with live output:

**Section A — Discovery**
Fetch and display `/.well-known/smart-configuration` from HAPI. Walk through each field and explain what a SMART client uses it for.

**Section B — Token anatomy**
Obtain a Client Credentials token. Decode and display the header, payload, and a note about the signature (you can't display it meaningfully, but explain what it is). Annotate each claim with its purpose.

**Section C — Authenticated FHIR access**
Make three requests: unauthenticated (expect 401), with a valid token (expect 200), and with an insufficient scope (expect 403). Display the full request and response for each, including headers.

**Section D — Token expiry and refresh simulation**
Show the token lifecycle: request a token, display its `exp`, make a request, simulate expiry (by manipulating the cached `expires_at`), show the automatic re-request, make another FHIR call with the fresh token.

> **Role relevance:** When a customer reports "my integration stopped working overnight," the most common causes are: token expiry with no refresh logic, JWKS key rotation (Keycloak rotates keys; old tokens signed with the previous key fail after rotation), or a scope that was revoked. The exercises in Step 5.5 and this notebook give you a complete diagnostic framework to work through any of those scenarios.

---

### Stretch: Authorization Code + PKCE with FastAPI

This stretch implements a browser-based login using your FastAPI background. You need two routes:

*Initiate login* (`GET /login`): generate a PKCE `code_verifier` (a random 32-byte URL-safe string), hash it to a `code_challenge` (SHA-256, base64url-encoded), store the `code_verifier` in the session, and redirect the browser to Keycloak's authorization endpoint with parameters: `response_type=code`, `client_id`, `redirect_uri`, `scope` (include `openid fhirUser` for OIDC), `code_challenge`, `code_challenge_method=S256`, and a `state` parameter (a random value you generate to prevent CSRF).

*Callback* (`GET /callback`): receive the `code` and `state` from Keycloak's redirect. Verify `state` matches what you stored. POST to Keycloak's token endpoint with `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id`, and the `code_verifier` from the session. Receive the access token, ID token, and refresh token.

After a successful callback:
- Decode the ID token and display the user's name/email
- Extract the `fhirUser` claim — it's a FHIR reference like `Practitioner/abc123`
- Use the access token to make a FHIR request (e.g., `GET /fhir/Patient`) and display the result

**Session management**: FastAPI doesn't have sessions built in — use `starlette.middleware.sessions.SessionMiddleware` with a secret key (add to `.env`). Store `code_verifier` and `state` in the session between the two routes.

**What this teaches**: the full Authorization Code + PKCE flow; the difference between the ID token (who is the user) and the access token (what are they allowed to do); why the back-channel code exchange is separate from the browser redirect (security: the token never touches the browser URL bar).

---

### Stretch: SMART Standalone Launch

SMART Standalone Launch is Authorization Code flow initiated by the app (not the EHR) with SMART-specific additions. The key difference from plain Authorization Code: the app discovers the auth endpoints from `/.well-known/smart-configuration` (instead of hardcoding them), and the token response may include a `patient` context claim identifying which patient the session is scoped to.

To exercise this: in the Keycloak `nxt-webapp` client, add a protocol mapper that includes a `patient` claim in the token response (hardcode a Patient ID from your HAPI data for the lab). In your FastAPI app, after the callback, read the `patient` claim and use it to fetch `GET /fhir/Patient/{patient-id}` with the access token. This simulates how a patient portal knows which patient's data to display after login.

---

## Phase 6 — C-CDA to FHIR Mapper

*Goal: generate Synthea C-CDA output, parse it, and map selected sections to FHIR resources.*

### Step 6.1 — Background: C-CDA and its role

C-CDA (Consolidated Clinical Document Architecture) is the dominant legacy format for clinical document exchange. It uses HL7 v3 / CDA with a set of defined document templates. The key document types:

- **Continuity of Care Document (CCD)**: the full medical summary, used for patient transitions
- **Referral Note**: specialist referrals
- **Discharge Summary**: post-hospitalization summary

C-CDA uses XML. Each document has a `ClinicalDocument` root, a `header` (patient demographics, provider info, timestamps), and a `body` with sections. Each section contains structured entries (coded clinical data) and a human-readable `<text>` block.

The HIE ingest problem: an organization sends C-CDA documents; your platform needs to ingest them as FHIR resources. The C-CDA-to-FHIR mapper is the "front door" of the ingest pipeline.

### Step 6.2 — Generate Synthea C-CDA output

Synthea can export C-CDA alongside or instead of FHIR:

```
java -jar synthea-with-dependencies.jar \
  -p 5 -s 1234 \
  --exporter.ccda.export true \
  --exporter.fhir.export false \
  Virginia "Fairfax"
```

Output: `./output/ccda/` — one `.xml` file per patient.

Examine one XML file before writing any code. Understand the namespace declarations, the `ClinicalDocument` root, the `component/structuredBody/component/section` pattern, and the entry structure within a section.

### Step 6.3 — Parsing C-CDA with `lxml`

`lxml` is the right tool for C-CDA. Key concepts:

- C-CDA uses XML namespaces extensively. The default namespace is `urn:hl7-org:v3`. You must declare this in every XPath expression: `doc.xpath('//hl7:section', namespaces={'hl7': 'urn:hl7-org:v3'})`.
- Each section has a `templateId` that identifies the section type (e.g., `2.16.840.1.113883.10.20.22.2.6.1` is the Allergies section).
- Entries within a section contain `act` or `observation` elements with coded values in `code` and `value` elements.

Write a `CcdaDocument` class in `lib/ccda_parser.py` that:
- Accepts a file path and parses it with lxml
- Exposes methods for extracting sections by template ID
- Exposes a method to get the patient's demographics from the header

### Step 6.4 — Map C-CDA sections to FHIR resources

Implement mappers for two sections as concrete examples:

**Allergies section → FHIR `AllergyIntolerance`**

The C-CDA Allergies section contains `act` entries. Each act has:
- `participant/participantRole/playingEntity/code` — the substance (usually RxNorm or NDF-RT)
- `entryRelationship/observation/value` — the reaction type (SNOMED)
- `effectiveTime` — onset date (may be a `low` element, a `high` element, or both)

Map each entry to an `AllergyIntolerance` resource. Key mapping decisions:
- C-CDA `statusCode` (`active`, `completed`, etc.) → FHIR `AllergyIntolerance.clinicalStatus`
- C-CDA `criticality` observation → FHIR `AllergyIntolerance.criticality`

**Problems section → FHIR `Condition`**

The Problems section contains `act` entries with `entryRelationship/observation` sub-entries. The observation `value` element contains the SNOMED or ICD-10 code. Map to `Condition.code.coding`.

### Step 6.5 — Post mapped resources to HAPI

After mapping, construct a FHIR `transaction` Bundle containing the mapped resources and post it to HAPI. Use `fhir.resources` here — constructing a Bundle by hand in raw dict is error-prone. The `AllergyIntolerance` and `Bundle` models will catch structural mistakes before the round-trip.

Validate the posted resources using `server_validate()`. Compare the OperationOutcome from a C-CDA-mapped resource against a Synthea-generated FHIR resource — the mapping will likely have gaps that Synthea doesn't.

> **Role relevance:** "HL7 v2, CCDA documents, and other legacy feeds" is named in the PD. The C-CDA mapper demonstrates that you understand both the source format and the target format, and can write the transformation logic — exactly the "data ingestion and transformation pipeline" work the role describes.

---

## Cross-cutting considerations

### Keeping the `lib/fhir_client.py` clean

As you add phases, resist the temptation to add one-off helpers to `fhir_client.py`. It should contain only:
- Configuration (FHIR_BASE, HEADERS)
- Generic FHIR patterns (pagination, $validate)
- The SMART client (Phase 5)

Phase-specific logic (the gap checker, the census, the C-CDA mapper) belongs in the scripts, notebooks, or tests that use it.

### Notebook discipline

Notebooks have a known problem: cell execution order. A notebook whose cells run in order 1–2–3–4 but were written and re-run in order 4–3–1–2 may have hidden state bugs. Before committing a notebook, restart the kernel and run all cells from top to bottom (`Kernel → Restart & Run All`). If it fails, fix it. A notebook that only runs in your current session isn't trustworthy.

Also: keep notebooks focused on one analytical question each. The four notebooks in the plan are already scoped that way — don't let `01_rest_exploration.ipynb` expand into a general-purpose scratch pad.

### Incrementalism and the interview

Each phase produces a working artifact. By the time you've completed all six phases, you have:

1. A shared FHIR client library (`lib/fhir_client.py`, `lib/smart_client.py`)
2. A data loader with ingestion-ordering logic (`scripts/load_synthea.py`)
3. A validation script with US Core and terminology checks (`scripts/validate.py`)
4. Five Jupyter notebooks: REST exploration, US Core validation, terminology census, DuckDB analytics, and SMART auth flow
5. A parametrized pytest suite that runs as a data-quality gate (`tests/`)
6. A DuckDB analytics layer demonstrating reporting-consistency investigation
7. A production-realistic SMART-on-FHIR auth stack: Keycloak + HAPI + `SmartFhirClient` with Client Credentials and Authorization Code flows
8. A C-CDA parser and FHIR mapper (`lib/ccda_parser.py`)

Any one of these is a concrete talking point. The combination maps directly to every bullet in the position description's Key Responsibilities section.

---

## Quick reference

### Environment commands

```bash
# Activate venv
source .venv/bin/activate

# Install runtime deps
pip install -r requirements.txt

# Install dev deps
pip install -r requirements-dev.txt

# Start full Docker stack (HAPI + Postgres + Keycloak + Keycloak-DB)
docker compose up -d

# Check stack health (all services should show "healthy" or "running")
docker compose ps

# Stop stack (keeps data volumes)
docker compose stop

# Stop and wipe all data volumes
docker compose down -v

# View HAPI logs
docker compose logs hapi-fhir -f

# View Keycloak logs
docker compose logs keycloak -f
```

### Script commands

```bash
# Load Synthea data
python scripts/load_synthea.py data/fhir

# Run validation checks
python scripts/validate.py

# Run test suite
pytest tests/ -v

# Run tests excluding slow ($validate round-trips)
pytest tests/ -v -m "not slow"

# Start Jupyter
jupyter notebook notebooks/
```

### Key service URLs

```
HAPI FHIR UI:             http://localhost:8080/
HAPI REST base:           http://localhost:8080/fhir
HAPI SMART discovery:     http://localhost:8080/fhir/.well-known/smart-configuration
HAPI CapabilityStatement: http://localhost:8080/fhir/metadata

Keycloak Admin Console:   http://localhost:8180/
Keycloak realm base:      http://localhost:8180/realms/nxt-lab
Keycloak OIDC discovery:  http://localhost:8180/realms/nxt-lab/.well-known/openid-configuration
Keycloak token endpoint:  http://localhost:8180/realms/nxt-lab/protocol/openid-connect/token
Keycloak JWKS endpoint:   http://localhost:8180/realms/nxt-lab/protocol/openid-connect/certs
```

### Key FHIR endpoints

```
GET  /fhir/metadata                          CapabilityStatement
GET  /fhir/{ResourceType}                    Search
GET  /fhir/{ResourceType}/{id}               Read
GET  /fhir/{ResourceType}/{id}/$everything   Full record
POST /fhir                                   Transaction bundle
POST /fhir/{ResourceType}/$validate          Validate resource
GET  /fhir/$export                           Bulk export (async)
```

### `.env` variables (full set across all phases)

```
# Phase 0 — FHIR server
FHIR_BASE=http://localhost:8080/fhir

# Phase 5 — Keycloak / SMART
KEYCLOAK_TOKEN_URL=http://localhost:8180/realms/nxt-lab/protocol/openid-connect/token
CLIENT_ID=nxt-backend
CLIENT_SECRET=<from Keycloak admin console>
SMART_SCOPE=system/*.read

# Phase 5 stretch — FastAPI web app
WEBAPP_CLIENT_ID=nxt-webapp
WEBAPP_REDIRECT_URI=http://localhost:8000/callback
SESSION_SECRET=<random string>
```
