from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from control_plane.keys import ManagementClaims


class Scope(StrEnum):
    """What a management credential may do; org and instance row-scoping are a separate axis.

    A scope restricts the credential, never expands it: a token minted without scopes carries the
    owning user's full authority, an explicit list is a restriction that also excludes scopes
    invented later. Roles arrive later as named bundles over these same values.

    Orgs and workspaces split their lifecycle three ways because founding a tenant and destroying
    one with everything inside it are each a different privilege from governing one day to day:
    :create founds, :write governs, :delete destroys. Elsewhere :write still covers all three.
    """

    inference_keys_read = "inference-keys:read"
    inference_keys_write = "inference-keys:write"
    workspaces_read = "workspaces:read"
    workspaces_create = "workspaces:create"
    workspaces_write = "workspaces:write"
    workspaces_delete = "workspaces:delete"
    bundles_read = "bundles:read"
    bundles_write = "bundles:write"
    events_read = "events:read"
    data_planes_read = "data-planes:read"
    provider_credentials_read = "provider-credentials:read"
    provider_credentials_write = "provider-credentials:write"
    taxonomy_read = "taxonomy:read"
    taxonomy_write = "taxonomy:write"
    orgs_read = "orgs:read"
    orgs_create = "orgs:create"
    orgs_write = "orgs:write"
    orgs_delete = "orgs:delete"
    users_read = "users:read"
    users_write = "users:write"
    activity_read = "activity:read"
    management_keys_read = "management-keys:read"
    management_keys_write = "management-keys:write"
    instance_keys_read = "instance-keys:read"
    instance_keys_write = "instance-keys:write"
    sync = "sync"


ALL_SCOPES: frozenset[str] = frozenset(scope.value for scope in Scope)


def allowed(claims: ManagementClaims, scope: Scope) -> bool:
    return scope.value in claims.scopes
