"""The bundle: how policy reaches the data plane.

One immutable request-path bundle set, two sources. remote polls the control plane and validates
bundles; local compiles a hand-written file. The request path never learns the source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from data_plane.bundle.base import BundleSource
from data_plane.bundle.config import BundleConfig, LocalBundleConfig, RemoteBundleConfig
from data_plane.bundle.holder import BundleHolder, BundleSnapshot
from data_plane.bundle.local import LocalBundleSource
from data_plane.bundle.remote import RemoteBundleSource

if TYPE_CHECKING:
    import aiohttp

__all__ = ["BundleConfig", "BundleHolder", "BundleSnapshot", "BundleSource", "LocalBundleConfig", "RemoteBundleConfig", "build_bundle_source"]


def build_bundle_source(
    config: BundleConfig,
    holder: BundleHolder,
    http_client: aiohttp.ClientSession,
) -> BundleSource:
    if isinstance(config, LocalBundleConfig):
        return LocalBundleSource(config, holder)
    return RemoteBundleSource(config, holder, http_client)
