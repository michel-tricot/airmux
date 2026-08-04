from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import typer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from dotenv import set_key

from contract import BundleV1, Catalog, KeyEntry, ModelEntry, ProviderEntry, mint_api_token, sign_bundle

app = typer.Typer(name="airllm", no_args_is_help=True)


def _load_or_create_key(key_path: Path) -> Ed25519PrivateKey:
    if key_path.exists():
        loaded = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        if not isinstance(loaded, Ed25519PrivateKey):
            typer.echo(f"{key_path} is not an Ed25519 key", err=True)
            raise typer.Exit(1)
        return loaded
    key = Ed25519PrivateKey.generate()
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return key


@app.command()
def seed(  # noqa: PLR0913, PLR0917 CLI options are a flat namespace by design
    cache_dir: str = ".airllm",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
    upstream_model: str = "",
    credential_ref: str = "env:OPENAI_API_KEY",
    write_env: bool = True,
) -> None:
    """Write a signed dev bundle to the data plane cache dir and print a caller token."""
    cache = Path(cache_dir).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    private_key = _load_or_create_key(cache / "signing.key")
    now = datetime.now(tz=UTC)
    bundle = BundleV1(
        bundle_id=uuid4(),
        org_id="org-dev",
        issued_at=now,
        expires_at=now + timedelta(hours=24),
        keys=[KeyEntry(key_id="k-dev", org_id="org-dev", allowed_models=["*"])],
        revocations=[],
        catalog=Catalog(
            providers=[ProviderEntry(provider_id="openai", kind="openai_compatible", base_url=base_url, credential_ref=credential_ref)],
            models=[
                ModelEntry(
                    model_id=model,
                    provider_id="openai",
                    upstream_model=upstream_model or model,
                    input_price_per_mtok=0.0,
                    output_price_per_mtok=0.0,
                    context_window=128000,
                    capabilities=["streaming", "tools"],
                )
            ],
        ),
    )
    signed = sign_bundle(bundle, private_key, "k1")
    (cache / "bundle.json").write_text(signed.model_dump_json(indent=2), encoding="utf-8")
    public_b64 = base64.b64encode(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).decode("ascii")
    token = mint_api_token("k-dev", "org-dev", private_key, now)
    if write_env:
        env_path = Path(".env")
        env_path.touch(exist_ok=True)
        for k, v in {"GW_CACHE_DIR": str(cache), "GW_BUNDLE_PUBLIC_KEY": public_b64, "AIRLLM_TOKEN": token}.items():
            set_key(env_path, k, v)
        typer.echo(f"wrote {env_path.resolve()}")
        typer.echo(f"put your provider key there too: {credential_ref.removeprefix('env:')}=sk-...")
    else:
        typer.echo(f"export GW_CACHE_DIR={cache}")
        typer.echo(f"export GW_BUNDLE_PUBLIC_KEY={public_b64}")
        typer.echo(f"export AIRLLM_TOKEN={token}")
    typer.echo("")
    typer.echo("start:  uv run data-plane")
    typer.echo("test:   source .env")
    typer.echo("        curl -s localhost:8080/v1/chat/completions \\")
    typer.echo('          -H "Authorization: Bearer $AIRLLM_TOKEN" -H "Content-Type: application/json" \\')
    typer.echo(f'          -d \'{{"model": "{model}", "messages": [{{"role": "user", "content": "say hi"}}]}}\'')


@app.command("compile")
def compile_bundle() -> None:
    raise NotImplementedError


@app.command()
def verify() -> None:
    raise NotImplementedError


@app.command()
def loadgen() -> None:
    raise NotImplementedError
