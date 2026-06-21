# ---------------------------------------------------------------------
# medicasoft-nxt-app/lib/fhir_client.py
# ---------------------------------------------------------------------
# A shared module that performs a few essential tasks
# ---------------------------------------------------------------------

import os
from dotenv import load_dotenv
import httpx

load_dotenv()

FHIR_BASE_URL = os.getenv("FHIR_BASE_URL", "http://localhost:8080/fhir")

# GET requests: Accept only — do not send Content-Type on body-less requests.
HEADERS = {"Accept": "application/fhir+json"}

# POST/PUT requests: both headers required.
POST_HEADERS = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}


def get_all(client: httpx.Client, resource_type: str, **params) -> list[dict]:
    """Page through a search result set, following Bundle 'next' links."""
    params.setdefault("_count", 200)
    url, out = f"{FHIR_BASE_URL}/{resource_type}", []
    while url:
        response = client.get(url, params=params, headers=HEADERS)
        response.raise_for_status()
        bundle = response.json()
        out += [e["resource"] for e in bundle.get("entry", [])]
        params = None  # next link already carries the cursor; params={} strips query params in httpx
        url = next((l["url"] for l in bundle.get("link", []) if l["relation"] == "next"), None)
    return out


def server_validate(client: httpx.Client, resource: dict) -> dict:
    """Authoritative, version-correct validation via the server's $validate.
    Base-spec validation works out of the box; profile validation needs the
    US Core IG package loaded into HAPI (see README)."""
    rt = resource["resourceType"]
    return client.post(
        f"{FHIR_BASE_URL}/{rt}/$validate",
        json=resource,
        headers=POST_HEADERS,
    ).json()
