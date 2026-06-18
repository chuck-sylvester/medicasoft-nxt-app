# medicasoft-nxt-app

This is a learning project to help me learn about and build integrations with the MedicaSoft NXT Platform (https://www.medicasoft.com/nxt). The information below is an initial plan for performing this experimentation, but is subject to change based on feedback from Claude. For example, I want to ensure that the project follows "Pythonic" best practices, uses a local python environment (.venv), uses Python version 3.12, and uses root-level .env and requirements.txt files. I would also like to organize the project into a proper folder structure. I would like to use pip as opposed to uv.

The goal is to stand up a local development environment that supports learning more about the NXT Platform and technology stack that would be used in support of the position described in the document, position-description.txt.

I am comfortable building applications using a FastAPI + HTMX + Jinja2 Templates + HTTPX tech stack, but am open to performing some or all of this using Python Jupyter Notebooks, if that is a useful thing to do.

As a first step, I will ask Claude to review this repository and provide feedback and recommendations to enure good alignment with the position description and anticipated technologies that will be used in this role. I am open to significant change if recommended after the Claude initial review.

---

This project attempts to mirror a development environment that supports the work of a **MedicaSoft Solution Engineer**. An initial guess is as follows:  

 - a native-FHIR R4 repository
 - FHIR REST APIs
 - terminology
 - an analytics-warehouse  
 
 NXT's repository is Couchbase under the hood and the warehouse is Redshift, but from a *customer-facing troubleshooting* perspective the work is FHIR-API-shaped, which can simulated via HAPI FHIR + Synthea.

This repository, toolset, and workflow is designed to match the position description's day-to-day scope:  

> Writing queries, scripts, or lightweight tooling to investigate issues, validate integrations, and resolving FHIR resource integrity and mapping, terminology and code set alignment, and downstream analytics and reporting consistency.

---

## Prerequisites

- Docker + Docker Compose
- Java 17+ (to run the Synthea jar)
- Python 3.11+ with `uv` (your usual). One dependency: `uv pip install httpx`
  (add `duckdb` and `fhir.resources` for the optional legs)

---

## 1. Stand up the FHIR repository

```bash
docker compose up -d
# UI:        http://localhost:8080/
# CapStmt:   http://localhost:8080/fhir/metadata
# REST base: http://localhost:8080/fhir
```

`GET /fhir/metadata` returns the CapabilityStatement — the same artifact you'd read to understand *any* FHIR server's conformance, including NXT's. Get in the habit of diffing it against what a customer claims is supported.

## 2. Generate US Core / USCDI data

The PD calls out US Core / USCDI explicitly, so generate profiled data — not vanilla R4. The flags below are the ones that matter.

```bash
curl -L -o synthea-with-dependencies.jar \
  https://github.com/synthetichealth/synthea/releases/download/master-branch-latest/synthea-with-dependencies.jar

java -jar synthea-with-dependencies.jar \
  -p 25 -s 1234 \
  --exporter.fhir.use_us_core_ig true \
  --exporter.fhir.us_core_version 6.1.0 \
  --exporter.fhir.transaction_bundle true \
  Virginia "Fairfax"
# Output -> ./output/fhir/  (one transaction Bundle per patient,
#           plus hospitalInformation*.json and practitionerInformation*.json)
```

Enabling US Core also makes Synthea emit resources you only get with the IG on — `CareTeam`, `Device`, `DocumentReference`, `Location`, `Medication`, `PractitionerRole`, `Provenance` — which is what an HIE feed really looks like.

## 3. Load into HAPI

```bash
FHIR_BASE=http://localhost:8080/fhir python load_synthea.py ./output/fhir
```

`load_synthea.py` posts the infrastructure bundles first (the dependency-ordering gotcha) and prints the server's `OperationOutcome` on any failure — your first triage artifact.

## 4. Explore the REST API the way a customer does

```bash
B=http://localhost:8080/fhir
curl "$B/Patient?_count=5"
curl "$B/Patient?name=Smith&birthdate=ge1960-01-01"
curl "$B/Condition?_include=Condition:patient&_count=5"          # _include
curl "$B/Observation?code=http://loinc.org|8867-4"               # terminology-scoped search
curl "$B/Patient/<id>/\$everything"                              # full record pull
```

Drill on search semantics: `_include` / `_revinclude`, chained params (`Observation?patient.name=...`), `_has`, `$everything`. Knowing *why* a customer's query returns the wrong set is most of this job.

## 5. Triage: integrity, conformance, terminology

```bash
FHIR_BASE=http://localhost:8080/fhir python validate.py
```

This reports US Core element/extension gaps on Patients, runs the server's `$validate` on a sample, and prints a CodeSystem census across Conditions and Observations (LOINC / SNOMED / RxNorm / ICD-10 / CVX). That census is the fast way to catch the classic HIE problem — a feed sending local codes where the consumer expects a standard system.

**Profile validation server-side (optional):** base-spec `$validate` works out of the box; to validate against `us-core-patient` etc., load the IG by mounting an `application.yaml` overlay with:

```yaml
hapi:
  fhir:
    implementationguides:
      us_core:
        name: hl7.fhir.us.core
        version: 6.1.0
```

…then mount it into the container at `/app/config/application.yaml`.

## 6. The analytics-warehouse leg (reporting consistency)

NXT feeds a Redshift warehouse off the FHIR repository; the recurring ticket is "the warehouse count doesn't match the API." Reproduce that loop locally by flattening FHIR JSON into SQL. DuckDB is the zero-infra stand-in (the SQL transfers straight to Redshift/Snowflake/BigQuery later):

```python
import duckdb, httpx
B = "http://localhost:8080/fhir"
conds = [e["resource"] for e in
         httpx.get(f"{B}/Condition", params={"_count": 1000}).json().get("entry", [])]
duckdb.sql("CREATE TABLE cond AS SELECT * FROM read_json_auto($conds)", params={"conds": conds})
# reporting-consistency check: conditions per patient, top SNOMED codes
duckdb.sql("""
  SELECT code.coding[1].code AS snomed, count(*) n
  FROM cond GROUP BY 1 ORDER BY n DESC LIMIT 10
""").show()
```

The "real" version of this is **SQL-on-FHIR v2 ViewDefinitions** (and tools like **Pathling**), which is exactly how a FHIR-native warehouse is populated. Worth reading — it's the conceptual model behind NXT's analytics layer and a strong thing to be able to discuss.

---

## PD responsibility -> what to practice here

| PD line | Practice in this lab |
| --- | --- |
| FHIR repository & resource persistence | HAPI; inspect via REST + `metadata` |
| FHIR REST APIs & interoperability workflows | Step 4 search semantics |
| FHIR resource integrity and mapping | `validate.py` + server `$validate` |
| US Core / USCDI requirements | US-Core-profiled Synthea + gap checks |
| Terminology and code set alignment | CodeSystem census in `validate.py` |
| Data ingestion / transformation pipelines | `load_synthea.py` ordering + OperationOutcome triage |
| Analytics warehouse & reporting consistency | Step 6 DuckDB / SQL-on-FHIR |
| HL7 v2 / C-CDA legacy feeds | Stretch goal below |

---

## Recommended stack / languages

Lead with what you already have — the PD describes *investigation tooling*, not platform development, so coherence beats breadth here.

- **Python (primary).** `httpx` + `fhir.resources` for scripted pulls and model validation, `pytest` for repeatable integration checks, `pandas`/`duckdb` for the warehouse leg. This is your stack already; no context-switch, and it's a literal match to "queries, scripts, or lightweight tooling."
- **SQL (close second).** The warehouse work names Redshift/Snowflake/BigQuery; NXT specifically uses **Redshift**. Practice now in DuckDB or Postgres — the dialect differences are small — then skim Redshift's distribution/sort-key model so you can speak to its performance characteristics.
- **FHIR REST fluency** is the real currency: search params, `_include`/ `_revinclude`, chaining, `$everything`, `$validate`, bulk `$export`.
- **Terminology:** LOINC, SNOMED CT, RxNorm, ICD-10-CM, CVX — know what each governs and where mismatches surface.
- **HL7 v2 + C-CDA** (legacy feeds, named in the PD): `hl7apy` or `python-hl7` for v2; `lxml`/XPath for C-CDA. Synthea also exports C-CDA, so you can practice the ingest-mapping side with the same generator.
- **FHIR server frameworks** the PD names — **HAPI, Firely, Smile CDR.** HAPI here transfers directly; Smile CDR is commercial HAPI, so the semantics you learn carry over one-to-one.
- **Couchbase / N1QL (awareness only).** You won't administer it as a Solution Engineer, but knowing how FHIR JSON maps to Couchbase documents — and how N1QL queries it — is a credible differentiator in the interview, since it's NXT's actual repository engine.

## Stretch goals

1. Point a SMART-on-FHIR client at HAPI to exercise the OAuth2 path NXT exposes for CMS Patient Access.
2. Generate Synthea **C-CDA** output and write a small mapper into FHIR — that's the ingest-engine "front door" problem in miniature.
3. Turn `validate.py` into a `pytest` suite so you have a reusable data-quality gate, the kind of "lightweight tooling" the PD rewards.
