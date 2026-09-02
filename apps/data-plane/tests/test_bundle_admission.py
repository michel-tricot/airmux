from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from conftest import MODEL, ORG, PROVIDER, make_bundle, make_credential, make_key

from contract import Catalog, ModelEntry
from data_plane.bundle.holder import BundleSet, BundleSnapshot

if TYPE_CHECKING:
    from collections.abc import MutableMapping


def _bundle(*, providers=(PROVIDER,), models=(MODEL,), credentials=(), keys=()):
    return make_bundle(catalog=Catalog(providers=list(providers), models=list(models), credentials=list(credentials)), keys=keys, org=ORG)


@pytest.mark.parametrize(
    ("bundle", "message"),
    [
        (_bundle(providers=(PROVIDER, PROVIDER)), "duplicate provider id"),
        (_bundle(models=(MODEL, MODEL)), "duplicate model id"),
        (_bundle(models=(MODEL.model_copy(update={"provider_id": "missing"}),)), "unknown provider"),
        (_bundle(providers=(PROVIDER.model_copy(update={"kind": "new_family"}),)), "unknown egress adapter"),
        (_bundle(models=(MODEL.model_copy(update={"egress_kind": "new_family"}),)), "unknown egress adapter"),
        (_bundle(credentials=(make_credential(service="missing"),)), "unknown provider"),
        (
            _bundle(credentials=(make_credential(org=make_key("other")[1].workspace_id),)),
            r"credential .* belongs to another organization",
        ),
    ],
)
def test_bundle_admission_rejects_inconsistent_catalogs(bundle, message):
    with pytest.raises(ValueError, match=message):
        BundleSnapshot.from_bundle(bundle)


def test_bundle_admission_rejects_a_key_owned_by_another_organization():
    key = make_key(org=make_key("other")[1].workspace_id)[1]

    with pytest.raises(ValueError, match=r"key .* belongs to another organization"):
        BundleSet.from_bundles((_bundle(keys=(key,)),))


def test_anthropic_models_must_carry_their_required_output_limit_in_the_bundle():
    provider = PROVIDER.model_copy(update={"kind": "anthropic"})
    model = MODEL.model_copy(update={"max_output_tokens": None})

    with pytest.raises(ValueError, match="max_output_tokens"):
        BundleSnapshot.from_bundle(_bundle(providers=(provider,), models=(model,)))


def test_snapshot_indexes_are_immutable():
    snapshot = BundleSnapshot.from_bundle(_bundle())
    mutable_index = cast("MutableMapping[str, ModelEntry]", snapshot.model_index)

    with pytest.raises(TypeError):
        mutable_index["other"] = MODEL
