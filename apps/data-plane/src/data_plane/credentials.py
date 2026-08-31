"""Which credentials a request may spend against, and how the value is fetched.

Split in two on purpose. The index is built once when a bundle is admitted, so the pure policy
function does dict lookups instead of scanning the catalog per request. The resolver is the only
thing here that does I/O, and it is deliberately not reachable from evaluate().
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from contract import CredentialEntry, SecretNotFoundError, SecretStoreUnavailableError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from uuid import UUID

    from contract import BundleV1, Secret, SecretStore

logger = logging.getLogger("data_plane")

CACHE_TTL_S = 300.0
NEGATIVE_TTL_S = 15.0
RATE_LIMIT_COOLDOWN_S = 30.0

type CredentialIndex = Mapping[tuple[UUID | None, str], tuple[CredentialEntry, ...]]


def index_credentials(bundle: BundleV1) -> CredentialIndex:
    """Credentials grouped by the tier that can spend them, each tier already in try order.

    The key is (workspace_id, provider) for a workspace credential, (org_id, provider) for an org
    one, and (None, provider) for a platform one. A workspace id and an org id cannot collide
    because both are uuids minted from the same space, so one flat dict serves all three tiers.
    """
    grouped: dict[tuple[UUID | None, str], list[CredentialEntry]] = {}
    for entry in bundle.catalog.credentials:
        owner = entry.ref.workspace_id or entry.ref.org_id
        grouped.setdefault((owner, entry.ref.service), []).append(entry)
    return {key: tuple(sorted(entries, key=lambda e: (e.priority, e.ref.name))) for key, entries in grouped.items()}


def candidates_for(index: CredentialIndex, workspace_id: UUID, org_id: UUID, provider: str) -> tuple[CredentialEntry, ...]:
    """The most specific tier holding anything: workspace, else org, else platform.

    Empty tiers cascade so a workspace that brought no key of its own still serves. A tier that has
    credentials is the tier, even if every one of them turns out to be broken: falling through on
    failure would move an org's spend onto the platform account without anyone asking.
    """
    for owner in (workspace_id, org_id, None):
        found = index.get((owner, provider))
        if found:
            return found
    return ()


class CredentialResolver:
    """Fetches credential values, caching what it gets.

    Keyed on (secret_id, version), so a rotation in the control plane invalidates by arriving in the
    next bundle with a higher version. No invalidation message, no TTL wait, and the old value stays
    cached and harmless until it ages out.

    The TTL exists only for a value edited in the store behind the control plane's back. Absence is
    cached briefly because it is a fact about the credential; unavailability is never cached because
    it is a fact about infrastructure, and a store that is down must not look like a missing key.
    """

    def __init__(self, store: SecretStore, ttl_s: float = CACHE_TTL_S, negative_ttl_s: float = NEGATIVE_TTL_S) -> None:
        self.store = store
        self.ttl_s = ttl_s
        self.negative_ttl_s = negative_ttl_s
        self._values: dict[tuple[UUID, int], tuple[float, Secret | None]] = {}
        self._locks: dict[tuple[UUID, int], asyncio.Lock] = {}
        self._cooldowns: dict[tuple[UUID, int], float] = {}

    def forget(self, entry: CredentialEntry) -> None:
        """Drop a cached value after upstream rejected it, so a key rotated out of band is refetched
        on the next attempt rather than at the end of the TTL."""
        key = (entry.ref.secret_id, entry.version)
        self._values.pop(key, None)
        lock = self._locks.get(key)
        if lock is not None and not lock.locked():
            self._locks.pop(key, None)

    def available(self, entries: tuple[CredentialEntry, ...]) -> tuple[CredentialEntry, ...]:
        now = time.monotonic()
        self._prune(now)
        return tuple(entry for entry in entries if self._cooldowns.get((entry.ref.secret_id, entry.version), 0) <= now)

    def rate_limit(self, entry: CredentialEntry) -> None:
        self._cooldowns[(entry.ref.secret_id, entry.version)] = time.monotonic() + RATE_LIMIT_COOLDOWN_S

    async def fetch(self, entry: CredentialEntry) -> Secret | None:
        """The value, or None when there is none. Raises only when the store could not answer.

        Single-flight per key: a cold cache under load would otherwise send one store request per
        concurrent request for the same credential.
        """
        key = (entry.ref.secret_id, entry.version)
        now = time.monotonic()
        self._prune(now)
        cached = self._values.get(key)
        if cached is not None and cached[0] > now:
            return cached[1]
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = self._values.get(key)
            if cached is not None and cached[0] > time.monotonic():
                return cached[1]
            return await self._load(key, entry)

    async def _load(self, key: tuple[UUID, int], entry: CredentialEntry) -> Secret | None:
        try:
            secret = await self.store.get(entry.ref)
        except SecretNotFoundError:
            logger.warning("credential %s (%s) is in the bundle but has no value in the store", entry.ref.name, entry.ref.secret_id)
            self._values[key] = (time.monotonic() + self.negative_ttl_s, None)
            return None
        except SecretStoreUnavailableError:
            self._locks.pop(key, None)
            raise
        self._values[key] = (time.monotonic() + self.ttl_s, secret)
        return secret

    def _prune(self, now: float) -> None:
        for key, (expires, _) in tuple(self._values.items()):
            if expires > now:
                continue
            self._values.pop(key, None)
            lock = self._locks.get(key)
            if lock is not None and not lock.locked():
                self._locks.pop(key, None)
        for key, expires in tuple(self._cooldowns.items()):
            if expires <= now:
                self._cooldowns.pop(key, None)
