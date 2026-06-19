#!/usr/bin/env python3
"""Load Synthea FHIR R4 *transaction* bundles into the local HAPI server.

Usage:
    python load_synthea.py ./synthea/output/fhir
    FHIR_BASE_URL=http://localhost:8080/fhir python load_synthea.py <dir>

Why the ordering matters: Synthea writes two infrastructure bundles
(hospitalInformation*.json, practitionerInformation*.json) that the patient
bundles reference. Load those first or the patient transactions fail their
reference resolution -- exactly the kind of "ingestion ordering" bug you'd
triage on the job.
"""
import glob
import json
import os
import sys

import httpx

from lib.fhir_client import FHIR_BASE_URL, HEADERS


def ordered_files(d: str) -> list[str]:
    infra = (
        sorted(glob.glob(os.path.join(d, "hospitalInformation*.json")))
        + sorted(glob.glob(os.path.join(d, "practitionerInformation*.json")))
    )
    infra_names = {os.path.basename(p) for p in infra}
    patients = sorted(
        p for p in glob.glob(os.path.join(d, "*.json"))
        if os.path.basename(p) not in infra_names
    )
    return infra + patients


def post_bundle(client: httpx.Client, path: str) -> httpx.Response:
    with open(path) as f:
        bundle = json.load(f)
    if bundle.get("type") != "transaction":
        raise ValueError(
            f"{os.path.basename(path)} is a '{bundle.get('type')}' bundle; "
            "re-run Synthea with --exporter.fhir.transaction_bundle true"
        )
    resp = client.post(FHIR_BASE_URL, json=bundle, headers=HEADERS)
    resp.raise_for_status()
    return resp


def main() -> None:
    out_dir = sys.argv[1] if len(sys.argv) > 1 else "./synthea/output/fhir"
    files = ordered_files(out_dir)
    if not files:
        sys.exit(f"No bundles found in {out_dir}")

    print(f"Loading {len(files)} bundles into {FHIR_BASE_URL}")
    with httpx.Client(timeout=180) as client:
        for i, path in enumerate(files, 1):
            name = os.path.basename(path)
            try:
                post_bundle(client, path)
                print(f"[{i}/{len(files)}] ok   {name}")
            except httpx.HTTPStatusError as e:
                # The server's OperationOutcome is your first triage artifact.
                snippet = e.response.text[:600]
                print(f"[{i}/{len(files)}] FAIL {name}  -> {e.response.status_code}\n{snippet}\n")
            except ValueError as e:
                print(f"[{i}/{len(files)}] SKIP {name}  -> {e}")


if __name__ == "__main__":
    main()
