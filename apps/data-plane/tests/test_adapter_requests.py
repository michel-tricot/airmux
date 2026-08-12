from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from conftest import MODEL, PROVIDER
from corpus import CORPUS, request_of
from jsonschema import Draft202012Validator

from contract import Secret
from data_plane.adapters import REGISTRY
from data_plane.canonical import CanonicalRequest

if TYPE_CHECKING:
    from jsonschema.protocols import Validator

SCHEMA_DIR = Path(__file__).resolve().parents[3] / "taxonomy" / "schemas" / "completion"

# The reference vendor per wire family: its own extracted schema arbitrates what the adapter renders.
REFERENCE_SCHEMA = {"openai_compatible": "oai.openai.request.json"}


def _validator(kind: str) -> Validator:
    schema = json.loads((SCHEMA_DIR / REFERENCE_SCHEMA[kind]).read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _adapter(kind: str):
    provider = PROVIDER.model_copy(update={"kind": kind})
    return REGISTRY[kind](provider, Secret("sk-test")), MODEL


@pytest.mark.parametrize("kind", sorted(REGISTRY))
@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c.name)
def test_every_corpus_case_renders_a_schema_valid_upstream_request(kind, case):
    """The provider's own published schema arbitrates, not a transcription of it."""
    adapter, model = _adapter(kind)
    upstream = adapter.transform_request(request_of(case), model)
    body = json.loads(upstream.body)
    errors = [f"{list(e.path)}: {e.message}" for e in _validator(kind).iter_errors(body)]
    assert not errors, "\n".join(errors)


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_the_upstream_request_names_the_upstream_model_and_spends_the_injected_credential(kind):
    adapter, model = _adapter(kind)
    upstream = adapter.transform_request(request_of(CORPUS[0]), model)
    assert json.loads(upstream.body)["model"] == model.upstream_model
    assert "sk-test" in upstream.headers.get("authorization", "") or "sk-test" in upstream.headers.get("x-api-key", "")


@pytest.mark.parametrize("kind", sorted(REGISTRY))
def test_extra_fields_do_not_reach_the_upstream(kind):
    """Until provider profiles land, an extra field is dropped and reported, never forwarded blind."""
    adapter, model = _adapter(kind)
    body = json.loads(request_of(CORPUS[0]).model_dump_json())
    request = CanonicalRequest.model_validate({**body, "frequency_penalty": 0.5})
    upstream = adapter.transform_request(request, model)
    assert "frequency_penalty" not in json.loads(upstream.body)
