"""The audit trigger mechanism, driven through the fat models with set_actor called directly.

These tests prove the triggers write correct rows (actions, snapshots, record ids, attribution)
for any ORM write. The link they deliberately fake, a real request's bearer token becoming the
stamped actor, is proven in test_deps.py.
"""

from __future__ import annotations

import pytest
from helpers import run_in_db, setup_db
from sqlalchemy.exc import DBAPIError
from sqlmodel import col

from control_plane.models import AuditLog, Org, OrgMembership, Provider, User, set_actor

ACTOR = "u-actor"


def _audit_rows(tmp_path) -> list[AuditLog]:
    return run_in_db(tmp_path, lambda: AuditLog.find(order_by=col(AuditLog.id)))


def _create_provider(tmp_path, base_url: str = "https://api.openai.com/v1"):
    async def create():
        await set_actor(ACTOR)
        provider = Provider(name="openai", kind="openai_compatible", base_url=base_url)
        await provider.save()
        return provider.id

    return run_in_db(tmp_path, create)


def test_create_update_and_delete_write_attributed_rows(tmp_path):
    setup_db(tmp_path)
    provider_id = _create_provider(tmp_path)

    async def saveless_update():
        await set_actor(ACTOR)
        provider = await Provider.first(Provider.name == "openai")
        assert provider is not None
        provider.base_url = "https://eu.api.openai.com/v1"

    run_in_db(tmp_path, saveless_update)

    async def delete():
        await set_actor(ACTOR)
        provider = await Provider.first(Provider.name == "openai")
        assert provider is not None
        await provider.delete()

    run_in_db(tmp_path, delete)

    creation, update, deletion = _audit_rows(tmp_path)
    assert (creation.table_name, creation.action) == ("provider", "create")
    assert (update.table_name, update.action) == ("provider", "update")
    assert (deletion.table_name, deletion.action) == ("provider", "delete")
    assert all(r.record_id == str(provider_id) and r.user_id == ACTOR and r.occurred_at is not None for r in (creation, update, deletion))
    assert creation.before is None
    assert creation.after is not None
    assert creation.after["base_url"] == "https://api.openai.com/v1"
    assert update.before is not None
    assert update.after is not None
    assert update.before["base_url"] == "https://api.openai.com/v1"
    assert update.after["base_url"] == "https://eu.api.openai.com/v1"
    assert deletion.before is not None
    assert deletion.after is None


def test_snapshots_exclude_database_owned_timestamps(tmp_path):
    setup_db(tmp_path)
    _create_provider(tmp_path)

    creation = _audit_rows(tmp_path)[0]
    assert creation.after is not None
    for column in ("created_at", "updated_at", "deleted_at"):
        assert column not in creation.after


def test_composite_primary_keys_join_in_record_id(tmp_path):
    setup_db(tmp_path)

    async def build():
        await set_actor(ACTOR)
        user = User(email="m@example.com", name="m")
        await user.save()
        org = await Org.create("O1")
        await OrgMembership(user_id=user.id, org_id=org.id).save()
        return user.id, org.id

    user_id, org_id = run_in_db(tmp_path, build)

    async def remove():
        await set_actor(ACTOR)
        membership = await OrgMembership.get((user_id, org_id))
        assert membership is not None
        await membership.delete()

    run_in_db(tmp_path, remove)

    deletion = next(r for r in _audit_rows(tmp_path) if (r.table_name, r.action) == ("org_membership", "delete"))
    assert deletion.record_id == f"{user_id}/{org_id}"
    assert deletion.before is not None
    assert deletion.before["user_id"] == str(user_id)
    assert deletion.before["org_id"] == str(org_id)
    assert deletion.after is None


def test_noop_flush_writes_no_rows(tmp_path):
    setup_db(tmp_path)
    _create_provider(tmp_path)

    async def touch_with_same_value():
        provider = await Provider.first(Provider.name == "openai")
        assert provider is not None
        provider.base_url = provider.base_url

    run_in_db(tmp_path, touch_with_same_value)

    assert [(r.table_name, r.action) for r in _audit_rows(tmp_path)] == [("provider", "create")]


def test_writes_without_an_actor_are_rejected(tmp_path):
    """The trigger closes the audit gap: an audited write with no stamped actor fails, never lands silently."""
    setup_db(tmp_path)
    with pytest.raises(DBAPIError, match="unattributed write to audited table"):
        run_in_db(tmp_path, lambda: Org.create("Ghost"))
    assert run_in_db(tmp_path, Org.find) == []
