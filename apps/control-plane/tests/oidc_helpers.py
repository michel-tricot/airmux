from __future__ import annotations

import time

from authlib.jose import JsonWebKey, jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://idp.test"
CLIENT_ID = "client-1"

_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_PEM = _KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
_PUBLIC_PEM = _KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
PUBLIC_JWK = JsonWebKey.import_key(_PUBLIC_PEM, {"kid": "t1", "use": "sig", "alg": "RS256"}).as_dict()

DISCOVERY = {
    "issuer": ISSUER,
    "authorization_endpoint": f"{ISSUER}/authorize",
    "token_endpoint": f"{ISSUER}/token",
    "jwks_uri": f"{ISSUER}/jwks",
}


def mint_id_token(nonce: str, sub: str = "idp-sub-1", email: str | None = "ada@corp.test", aud: str = CLIENT_ID, **overrides) -> str:
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": aud, "sub": sub, "name": "Ada", "iat": now, "exp": now + 300, "nonce": nonce, **overrides}
    if email is not None:
        claims.setdefault("email", email)
    encoded = jwt.encode({"alg": "RS256", "kid": "t1"}, claims, _PRIVATE_PEM)
    return encoded.decode() if isinstance(encoded, bytes) else encoded


def fake_idp(respx_mock):
    """Mock the issuer's discovery and JWKS routes; returns a hook that arms the token endpoint for one exchange."""
    respx_mock.get(f"{ISSUER}/.well-known/openid-configuration").respond(json=DISCOVERY)
    respx_mock.get(f"{ISSUER}/jwks").respond(json={"keys": [PUBLIC_JWK]})

    def arm_token(nonce: str, **overrides) -> None:
        respx_mock.post(f"{ISSUER}/token").respond(json={"id_token": mint_id_token(nonce, **overrides), "access_token": "at", "token_type": "Bearer"})

    return arm_token
