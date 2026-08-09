from __future__ import annotations

import api_models


class OrgCreate(api_models.OrgCreate):
    """Every resource gets a CLI spec subclassing its generated create model; CLI-side defaults go here."""


class ProviderCreate(api_models.ProviderIn):
    pass


class ModelCreate(api_models.ModelIn):
    pass
