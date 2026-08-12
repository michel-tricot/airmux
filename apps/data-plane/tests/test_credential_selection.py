from __future__ import annotations

import pytest
from conftest import make_credential

from contract import MemoryStoreConfig, Secret, SecretStore, SecretStoreUnavailableError
from data_plane.credentials import CredentialResolver


async def value_of(resolver, entry) -> str:
    """The resolved value, with the absent case as a failed assertion rather than an attribute error."""
    secret = await resolver.fetch(entry)
    assert secret is not None
    return secret.reveal()


async def test_the_resolver_fetches_and_caches():
    store = MemoryStoreConfig().build()
    entry = make_credential()
    await store.put(entry.ref, Secret("sk-value"))
    resolver = CredentialResolver(store)
    assert await value_of(resolver, entry) == "sk-value"
    await store.delete(entry.ref)
    assert await value_of(resolver, entry) == "sk-value"


async def test_a_rotation_busts_the_cache_without_an_invalidation_message():
    """The version is the cache key, so a rotated credential arriving in the next bundle is fetched
    again on its first use rather than at the end of the TTL."""
    store = MemoryStoreConfig().build()
    entry = make_credential()
    await store.put(entry.ref, Secret("first"))
    resolver = CredentialResolver(store)
    assert await value_of(resolver, entry) == "first"
    await store.put(entry.ref, Secret("second"))
    rotated = make_credential(version=2, secret_id=entry.ref.secret_id)
    assert await value_of(resolver, rotated) == "second"


async def test_a_credential_with_no_value_resolves_to_nothing():
    """The row and the value live in two systems, so a bundle can name a credential the store never
    received. That is a fact about the credential, so it is cached briefly."""
    resolver = CredentialResolver(MemoryStoreConfig().build())
    assert await resolver.fetch(make_credential()) is None


async def test_an_unavailable_store_raises_and_is_not_cached():
    """Infrastructure being down must not be remembered as a missing key, or a store that recovers
    stays invisible for the length of the negative TTL."""

    class Broken(SecretStore):
        kind = "broken"

        def __init__(self):
            self.calls = 0

        async def get(self, ref):
            self.calls += 1
            raise SecretStoreUnavailableError(ref, "down")

    store = Broken()
    resolver = CredentialResolver(store)
    entry = make_credential()
    for _ in range(2):
        with pytest.raises(SecretStoreUnavailableError):
            await resolver.fetch(entry)
    assert store.calls == 2


async def test_forget_drops_a_value_upstream_rejected():
    store = MemoryStoreConfig().build()
    entry = make_credential()
    await store.put(entry.ref, Secret("stale"))
    resolver = CredentialResolver(store)
    await resolver.fetch(entry)
    await store.put(entry.ref, Secret("fresh"))
    resolver.forget(entry)
    assert await value_of(resolver, entry) == "fresh"
