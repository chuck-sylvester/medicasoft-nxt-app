#!/usr/bin/env python3
"""Triage bench: the checks a Solution Engineer runs against an HIE feed.

Covers three PD responsibilities directly:
  - "FHIR resource integrity and mapping"   -> structural + server $validate
  - "US Core / USCDI requirements"          -> must-have element / extension checks
  - "Terminology and code set alignment"    -> CodeSystem census across the data

Runnable with only httpx. The optional fhir.resources block shows local model
validation; pin the package to a FHIR-R4 build to avoid R4-vs-R4B drift.

    FHIR_BASE=http://localhost:8080/fhir python validate.py
"""
import collections
import os

import httpx

FHIR_BASE = os.environ.get("FHIR_BASE", "http://localhost:8080/fhir")
RACE_EXT = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
ETHNICITY_EXT = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"
HEADERS = {"Accept": "application/fhir+json"}


def get_all(client: httpx.Client, resource_type: str, **params) -> list[dict]:
    """Page through a search result set, following Bundle 'next' links."""
    params.setdefault("_count", 200)
    url, out = f"{FHIR_BASE}/{resource_type}", []
    while url:
        bundle = client.get(url, params=params, headers=HEADERS).raise_for_status().json()
        out += [e["resource"] for e in bundle.get("entry", [])]
        params = {}  # 'next' link already carries the cursor
        url = next((l["url"] for l in bundle.get("link", []) if l["relation"] == "next"), None)
    return out


def server_validate(client: httpx.Client, resource: dict) -> dict:
    """Authoritative, version-correct validation via the server's $validate.
    Base-spec validation works out of the box; profile validation needs the
    US Core IG package loaded into HAPI (see README)."""
    rt = resource["resourceType"]
    return client.post(
        f"{FHIR_BASE}/{rt}/$validate",
        json=resource,
        headers={"Content-Type": "application/fhir+json", **HEADERS},
    ).json()


def us_core_patient_gaps(patient: dict) -> list[str]:
    gaps = []
    if not patient.get("identifier"):
        gaps.append("missing identifier")
    if not patient.get("name"):
        gaps.append("missing name")
    if "gender" not in patient:
        gaps.append("missing gender")
    ext_urls = {e.get("url") for e in patient.get("extension", [])}
    if RACE_EXT not in ext_urls:
        gaps.append("missing us-core-race")
    if ETHNICITY_EXT not in ext_urls:
        gaps.append("missing us-core-ethnicity")
    return gaps


def terminology_census(resources: list[dict], path_field: str) -> collections.Counter:
    """Count which CodeSystems show up in <resource>.<path_field>.coding[].system."""
    systems = collections.Counter()
    for r in resources:
        for coding in (r.get(path_field) or {}).get("coding", []):
            systems[coding.get("system", "<none>")] += 1
    return systems


def main() -> None:
    with httpx.Client(timeout=120) as client:
        patients = get_all(client, "Patient")
        print(f"Patients loaded: {len(patients)}\n")

        # 1. US Core element/extension integrity
        with_gaps = [(p.get("id"), g) for p in patients if (g := us_core_patient_gaps(p))]
        print(f"US Core Patient gaps: {len(with_gaps)} of {len(patients)}")
        for pid, gaps in with_gaps[:5]:
            print(f"  Patient/{pid}: {', '.join(gaps)}")

        # 2. Server-side structural validation on one sample
        if patients:
            oo = server_validate(client, patients[0])
            issues = [i for i in oo.get("issue", []) if i.get("severity") in ("error", "fatal")]
            print(f"\n$validate on Patient/{patients[0].get('id')}: "
                  f"{len(issues)} error/fatal issue(s)")

        # 3. Terminology census across Conditions and Observations
        print("\nCondition.code systems in use:")
        for system, n in terminology_census(get_all(client, "Condition"), "code").most_common():
            print(f"  {n:6d}  {system}")
        print("\nObservation.code systems in use:")
        for system, n in terminology_census(get_all(client, "Observation"), "code").most_common():
            print(f"  {n:6d}  {system}")

    # Optional local model validation (uncomment after: uv pip install "fhir.resources")
    # from fhir.resources.R4B.patient import Patient
    # Patient.model_validate(patients[0])  # raises on structural problems


if __name__ == "__main__":
    main()
