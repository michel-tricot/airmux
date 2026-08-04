from __future__ import annotations

from pydantic import BaseModel, Field

from cli.api_models import KeyIn, ModelIn, OrgIn, ProviderIn


class OrgCreate(OrgIn):
    """Every resource gets a CLI spec subclassing its generated *In model; CLI-side defaults go here, like org_id on the others."""


class KeyCreate(KeyIn):
    org_id: str = Field("org-dev", description="Org the key belongs to")


class ProviderCreate(ProviderIn):
    org_id: str = Field("org-dev", description="Org the provider belongs to")


class ModelCreate(ModelIn):
    org_id: str = Field("org-dev", description="Org the model belongs to")


class BootstrapSpec(BaseModel):
    org: str
    providers: list[ProviderCreate] = Field(default_factory=list)
    models: list[ModelCreate] = Field(default_factory=list)
    keys: list[KeyCreate] = Field(default_factory=lambda: [KeyCreate()])
