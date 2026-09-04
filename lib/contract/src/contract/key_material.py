from __future__ import annotations

import base64
from typing import Annotated

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BeforeValidator, PlainSerializer


def private_key_to_b64(private_key: Ed25519PrivateKey) -> str:
    raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(raw).decode("ascii")


def private_key_from_b64(b64: str) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(base64.b64decode(b64))


def public_key_to_b64(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def public_key_from_b64(b64: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(b64))


def _private_key_before(value: object) -> object:
    return private_key_from_b64(value) if isinstance(value, str) else value


def _public_key_before(value: object) -> object:
    return public_key_from_b64(value) if isinstance(value, str) else value


Ed25519PrivateKeyB64 = Annotated[Ed25519PrivateKey, BeforeValidator(_private_key_before), PlainSerializer(private_key_to_b64, return_type=str)]
Ed25519PublicKeyB64 = Annotated[Ed25519PublicKey, BeforeValidator(_public_key_before), PlainSerializer(public_key_to_b64, return_type=str)]
