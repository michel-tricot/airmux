from __future__ import annotations

from cli.api_models import KeyIn, ModelIn, OrgIn, ProviderIn


class OrgCreate(OrgIn):
    """Every resource gets a CLI spec subclassing its generated *In model; CLI-side defaults go here."""


class KeyCreate(KeyIn):
    pass


class ProviderCreate(ProviderIn):
    pass


class ModelCreate(ModelIn):
    pass
