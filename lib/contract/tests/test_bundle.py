from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, cast

import pytest
from pydantic import ValidationError

from contract import BundleManifest, BundleV1, KeyEntry, ModelEntry, ProviderEntry, uuid7

if TYPE_CHECKING:
    from collections.abc import MutableMapping


def model_entry(**overrides: object) -> dict[str, object]:
    return {
        "model_id": "model",
        "provider_id": "provider",
        "upstream_model": "upstream",
        "input_price_per_mtok": "1",
        "output_price_per_mtok": "2",
        "cache_read_price_per_mtok": "0",
        "cache_write_price_per_mtok": "0",
        "context_window": 128000,
        "input_modalities": ["text"],
        "output_modalities": ["text"],
        "capabilities": ["streaming"],
        **overrides,
    }


def test_model_modalities_are_required_bundle_data():
    with pytest.raises(ValidationError):
        ModelEntry.model_validate(model_entry(input_modalities=None))
    with pytest.raises(ValidationError):
        ModelEntry.model_validate(model_entry(output_modalities=[]))


def test_model_prices_are_exact_and_serialize_as_strings():
    model = ModelEntry.model_validate(model_entry())

    assert model.input_price_per_mtok == Decimal(1)
    assert model.model_dump(mode="json")["input_price_per_mtok"] == "1"


def test_model_capabilities_use_the_policy_vocabulary():
    with pytest.raises(ValidationError):
        ModelEntry.model_validate(model_entry(capabilities=["visionary"]))


def test_inference_key_ids_are_opaque_strings():
    key = KeyEntry(
        key_id="external-key",
        org_id=uuid7(),
        workspace_id=uuid7(),
        user_id=uuid7(),
        token_hash="hash",
        authentication_source="inference_key",
        authentication_label="Production",
        principal_label="Checkout service",
        principal_type="service_account",
        workspace_label="Production",
    )
    assert key.key_id == "external-key"


@pytest.mark.parametrize("field", ["authentication_source", "authentication_label", "principal_label", "principal_type", "workspace_label"])
def test_bundle_keys_require_execution_time_attribution(field):
    key = {
        "key_id": "external-key",
        "org_id": uuid7(),
        "workspace_id": uuid7(),
        "user_id": uuid7(),
        "token_hash": "hash",
        "authentication_source": "inference_key",
        "authentication_label": "Production",
        "principal_label": "Checkout service",
        "principal_type": "service_account",
        "workspace_label": "Production",
    }
    del key[field]

    with pytest.raises(ValidationError):
        KeyEntry.model_validate(key)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("authentication_label", ""),
        ("authentication_label", "a" * 201),
        ("principal_label", ""),
        ("principal_label", "p" * 321),
        ("workspace_label", ""),
        ("workspace_label", "w" * 201),
    ],
)
def test_bundle_key_attribution_labels_are_bounded(field, value):
    payload = {
        "key_id": "external-key",
        "org_id": uuid7(),
        "workspace_id": uuid7(),
        "user_id": uuid7(),
        "token_hash": "hash",
        "authentication_source": "inference_key",
        "authentication_label": "Production",
        "principal_label": "Checkout service",
        "principal_type": "service_account",
        "workspace_label": "Production",
        field: value,
    }
    with pytest.raises(ValidationError):
        KeyEntry.model_validate(payload)


@pytest.mark.parametrize(
    ("authentication_source", "principal_type"),
    [("local", "human"), ("local", "service_account"), ("inference_key", "local"), ("playground", "local")],
)
def test_bundle_key_principal_kind_matches_authentication_source(authentication_source, principal_type):
    with pytest.raises(ValidationError, match="principal_type must match"):
        KeyEntry(
            key_id="external-key",
            org_id=uuid7(),
            workspace_id=uuid7(),
            user_id=uuid7(),
            token_hash="hash",
            authentication_source=authentication_source,
            authentication_label="Authentication",
            principal_label="Principal",
            principal_type=principal_type,
            workspace_label="Workspace",
        )


def test_empty_manifest_contains_only_bundle_references():
    assert BundleManifest(bundles=()).model_dump(mode="json") == {"bundles": []}


@pytest.mark.parametrize("identity", [{}, {"user_id": None}, {"user_id": "invalid"}])
def test_bundle_keys_require_principal_identity(identity):
    with pytest.raises(ValidationError):
        KeyEntry.model_validate({"key_id": "external", "org_id": uuid7(), "workspace_id": uuid7(), "token_hash": "hash", **identity})


def bundle_payload():
    org = str(uuid7())
    return {
        "bundle_id": str(uuid7()),
        "org_id": org,
        "issued_at": "2026-09-18T00:00:00Z",
        "keys": [
            {
                "key_id": "external",
                "org_id": org,
                "workspace_id": str(uuid7()),
                "user_id": str(uuid7()),
                "token_hash": "hash",
                "authentication_source": "inference_key",
                "authentication_label": "Production",
                "principal_label": "Checkout service",
                "principal_type": "service_account",
                "workspace_label": "Production",
            }
        ],
        "catalog": {
            "providers": [{"provider_id": "provider", "kind": "openai_compatible", "base_url": "https://example.com", "accepted_params": ["seed"]}],
            "models": [model_entry(parameter_support={"temperature": "supported"})],
            "credentials": [
                {"ref": {"purpose": "provider", "service": "provider", "name": "default", "secret_id": str(uuid7())}, "priority": 100, "version": 1}
            ],
        },
        "policies": [],
    }


@pytest.mark.parametrize("field", ["context_window", "max_output_tokens"])
@pytest.mark.parametrize("value", [-1, 0, 100_000_001])
def test_bundle_token_limits_reject_values_outside_the_domain(field, value):
    with pytest.raises(ValidationError):
        ModelEntry.model_validate(model_entry(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [("model_id", ""), ("model_id", "m" * 256), ("provider_id", "Invalid Provider"), ("upstream_model", ""), ("egress_kind", "bad-kind")],
)
def test_bundle_model_identifiers_are_constrained(field, value):
    with pytest.raises(ValidationError):
        ModelEntry.model_validate(model_entry(**{field: value}))


@pytest.mark.parametrize(("field", "value"), [("provider_id", ""), ("provider_id", "UPPER"), ("kind", ""), ("kind", "bad-kind")])
def test_bundle_provider_identifiers_are_constrained(field, value):
    with pytest.raises(ValidationError):
        ProviderEntry.model_validate({"provider_id": "provider", "kind": "openai_compatible", "base_url": "https://example.com", field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [("capabilities", ["streaming"] * 5), ("parameter_support", {str(index): "supported" for index in range(129)})],
)
def test_bundle_model_profiles_are_bounded(field, value):
    with pytest.raises(ValidationError):
        ModelEntry.model_validate(model_entry(**{field: value}))


@pytest.mark.parametrize("field", ["accepted_params", "param_aliases"])
def test_bundle_provider_profiles_are_bounded(field):
    value = ["seed"] * 257 if field == "accepted_params" else {str(index): "seed" for index in range(257)}
    with pytest.raises(ValidationError):
        ProviderEntry.model_validate({"provider_id": "provider", "kind": "openai_compatible", "base_url": "https://example.com", field: value})


@pytest.mark.parametrize("mode", ["validation", "serialization"])
def test_immutable_mapping_schemas_preserve_value_constraints(mode):
    support = ModelEntry.model_json_schema(mode=mode)["properties"]["parameter_support"]
    assert support == {
        "type": "object",
        "title": "Parameter Support",
        "maxProperties": 128,
        "additionalProperties": {"type": "string", "enum": ["supported", "unsupported"]},
    }
    aliases = ProviderEntry.model_json_schema(mode=mode)["properties"]["param_aliases"]
    assert aliases["additionalProperties"] == {"type": "string"}
    assert aliases["maxProperties"] == 256


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("keys", 0),
        ("catalog",),
        ("catalog", "providers", 0),
        ("catalog", "models", 0),
        ("catalog", "credentials", 0),
        ("catalog", "credentials", 0, "ref"),
    ],
)
def test_bundle_rejects_unknown_fields_at_every_level(path):
    payload = bundle_payload()
    target = payload
    for part in path:
        target = target[part]
    target["unknown"] = True
    with pytest.raises(ValidationError, match=r"extra_forbidden|unexpected_keyword_argument"):
        BundleV1.model_validate(payload)


@pytest.mark.parametrize("field", ["issued_at", "expires_at"])
@pytest.mark.parametrize("timestamp", ["2026-09-18T00:00:00", datetime(2026, 9, 18, tzinfo=UTC).replace(tzinfo=None)])
def test_bundle_requires_timezone_aware_timestamps(field, timestamp):
    payload = bundle_payload()
    target = payload if field == "issued_at" else payload["keys"][0]
    target[field] = timestamp
    with pytest.raises(ValidationError, match="timezone"):
        BundleV1.model_validate(payload)


def test_bundle_nested_collections_are_immutable_and_round_trip_as_json():
    payload = bundle_payload()
    bundle = BundleV1.model_validate(payload)
    catalog = bundle.catalog
    for entries in (
        bundle.keys,
        bundle.policies,
        catalog.providers,
        catalog.models,
        catalog.credentials,
        catalog.providers[0].accepted_params,
        catalog.models[0].input_modalities,
        catalog.models[0].output_modalities,
        catalog.models[0].capabilities,
    ):
        assert isinstance(entries, tuple)
        with pytest.raises(AttributeError):
            cast("list[object]", entries).clear()
    for mapping in (catalog.providers[0].param_aliases, catalog.models[0].parameter_support):
        with pytest.raises(TypeError):
            cast("MutableMapping[str, str]", mapping)["temperature"] = "unsupported"
    original = bundle.model_dump(mode="json")
    payload["catalog"]["models"][0]["parameter_support"]["temperature"] = "unsupported"
    assert bundle.model_dump(mode="json") == original
    assert BundleV1.model_validate_json(bundle.model_dump_json()) == bundle


def test_manifest_is_immutable_and_rejects_unknown_fields():
    manifest = BundleManifest.model_validate({"bundles": [{"org_id": str(uuid7()), "bundle_id": str(uuid7())}]})
    assert isinstance(manifest.bundles, tuple)
    for payload in ({"bundles": [], "unknown": True}, {"bundles": [{**manifest.bundles[0].model_dump(), "unknown": True}]}):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            BundleManifest.model_validate(payload)
