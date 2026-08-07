from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from control_plane.tokens import ManagementClaims


class Scope(StrEnum):
    """What a management credential may do; org and instance row-scoping are a separate axis.

    A scope restricts the credential, never expands it: a token minted without scopes carries the
    owning user's full authority, an explicit list is a restriction that also excludes scopes
    invented later. Roles arrive later as named bundles over these same values.
    """

    keys_read = "keys:read"
    keys_write = "keys:write"
    bundles_read = "bundles:read"
    bundles_write = "bundles:write"
    sso_read = "sso:read"
    sso_write = "sso:write"
    events_read = "events:read"
    instances_read = "instances:read"
    taxonomy_read = "taxonomy:read"
    taxonomy_write = "taxonomy:write"
    orgs_read = "orgs:read"
    orgs_write = "orgs:write"
    users_read = "users:read"
    users_write = "users:write"
    tokens_read = "tokens:read"
    tokens_write = "tokens:write"
    sync = "sync"


ALL_SCOPES: frozenset[str] = frozenset(scope.value for scope in Scope)


def allowed(claims: ManagementClaims, scope: Scope) -> bool:
    return scope.value in claims.scopes
