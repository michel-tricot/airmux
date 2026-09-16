from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ControlPlaneLink(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str = Field(min_length=1)
    management_key: str = Field(min_length=1)
