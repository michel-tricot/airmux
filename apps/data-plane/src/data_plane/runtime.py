from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from data_plane.bundle.holder import BundleHolder

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from data_plane.config import Config
    from data_plane.credentials import CredentialResolver
    from data_plane.outbox import EventOutbox


@dataclass
class AppState:
    config: Config | None = None
    bundle_verify_key: Ed25519PublicKey | None = None
    outbox: EventOutbox | None = None
    credentials: CredentialResolver | None = None


state = AppState()
holder = BundleHolder()
