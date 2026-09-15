from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import uvicorn
import yaml
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from contract.initialization import GENERATED_STATE_GITIGNORE, write_new_configuration
from contract.taxonomy import parse_taxonomy
from control_plane.app import create_app
from control_plane.authz import InstanceRole
from control_plane.bootstrap import bootstrap_data_plane
from control_plane.compiler import publish_changes
from control_plane.config import Settings, load_settings
from control_plane.db import standalone_transaction
from control_plane.fixtures import Fixtures, apply_fixtures
from control_plane.keys import new_management_key
from control_plane.migrate import current_revision, head_revision, run_migrations
from control_plane.models import Model, Org, User, set_actor
from control_plane.taxonomy import apply_taxonomy

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@dataclass(frozen=True)
class Publication:
    organization: str
    version: int


@dataclass(frozen=True)
class FixtureResult:
    fixtures: Fixtures
    publications: tuple[Publication, ...]
    models: int


@dataclass(frozen=True)
class TaxonomyResult:
    providers: int
    models: int
    publications: tuple[Publication, ...]


@dataclass(frozen=True)
class MigrationResult:
    database: str
    before: str | None
    after: str


@contextmanager
def database_errors() -> Iterator[None]:
    try:
        yield
    except SQLAlchemyError:
        message = "Database operation failed; check DATABASE_URL, database availability, and permissions"
        raise ValueError(message) from None


@contextmanager
def configuration_environment(config: Path) -> Iterator[None]:
    selected = os.environ.get("TOKKEEPER_CONFIG")
    os.environ["TOKKEEPER_CONFIG"] = str(config)
    try:
        yield
    finally:
        if selected is None:
            os.environ.pop("TOKKEEPER_CONFIG", None)
        else:
            os.environ["TOKKEEPER_CONFIG"] = selected


def bootstrap_keygen(path: Path) -> None:
    token, _ = new_management_key()
    write_new_configuration(path.parent, {path.name: token})


def initialize(directory: Path, console_url: str) -> None:
    console_url = Settings(console_url=console_url).console_url
    token, _ = new_management_key()
    bootstrap = "${file:.tokkeeper/dataplane.key}"
    secrets = {"kind": "file", "root": ".tokkeeper/secrets"}
    link = {"url": "http://127.0.0.1:8000", "token": bootstrap}
    config = {
        "control_plane": {
            "database": {"url": "${env:DATABASE_URL}"},
            "bootstrap": {"token": bootstrap},
            "console_url": console_url,
            "secrets": secrets,
        },
        "data_plane": {
            "bundle": {"kind": "remote", "control_plane": link, "cache_dir": ".tokkeeper/gateway"},
            "events": {"kind": "sqlite", "control_plane": link, "cache_dir": ".tokkeeper/gateway"},
            "secrets": secrets,
        },
    }
    write_new_configuration(
        directory,
        {
            ".tokkeeper/.gitignore": GENERATED_STATE_GITIGNORE,
            ".tokkeeper/dataplane.key": token,
            "tokkeeper.yml": yaml.safe_dump(config, sort_keys=False),
        },
    )


def serve(config: Path, *, host: str, port: int, dev: bool) -> None:
    os.environ["TOKKEEPER_CONFIG"] = str(config)
    if dev:
        run_migrations()
    uvicorn.run("control_plane.app:create_app", factory=True, host=host, port=port, reload=dev)


def migrate(config: Path) -> MigrationResult:
    with configuration_environment(config):
        url = load_settings(config).database.url
        with database_errors():
            before = current_revision(url)
            run_migrations()
        head = head_revision()
        if head is None:
            message = "The installed control plane has no migration head"
            raise ValueError(message)
        return MigrationResult(make_url(url).render_as_string(hide_password=True), before, head)


def export_openapi() -> str:
    return yaml.safe_dump(create_app(Settings()).openapi(), sort_keys=False, allow_unicode=True, width=120)


async def promote_owner(email: str, config: Path) -> tuple[str, bool]:
    email = User.normalize_email(email)
    with database_errors():
        async with standalone_transaction(load_settings(config).database.url):
            user = await User.first(User.email == email)
            if user is None:
                message = "account does not exist; ask its owner to sign up first"
                raise ValueError(message)
            if user.service_account:
                message = "instance authority belongs to a human account"
                raise ValueError(message)
            if user.instance_role == InstanceRole.owner:
                return email, True
            await set_actor(user.id)
            await User.change_instance_role(user.id, InstanceRole.owner)
    return email, False


async def _publish() -> tuple[Publication, ...]:
    organizations = {organization.id: organization.name for organization in await Org.find()}
    return tuple(Publication(organizations[bundle.org_id], bundle.version) for bundle in await publish_changes(datetime.now(tz=UTC)))


async def seed_fixtures(config: Path) -> FixtureResult:
    settings = load_settings(config)
    with database_errors():
        async with settings.secrets.build() as secret_store, standalone_transaction(settings.database.url):
            if settings.bootstrap is not None:
                await bootstrap_data_plane(settings.bootstrap)
            fixtures = await apply_fixtures(datetime.now(tz=UTC), secret_store)
            return FixtureResult(fixtures, await _publish(), len(await Model.find()))


async def apply_catalog(config: Path, path: Path) -> TaxonomyResult:
    taxonomy = parse_taxonomy(path)
    with database_errors():
        async with standalone_transaction(load_settings(config).database.url):
            await set_actor("root")
            providers, models = await apply_taxonomy(taxonomy)
            return TaxonomyResult(providers, models, await _publish())
