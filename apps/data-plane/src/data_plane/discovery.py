from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict
from starlette.responses import Response

from contract import Capability, Modality, ParameterSupport
from data_plane.auth import authenticate_request
from data_plane.egress.base import CanonicalError
from data_plane.errors import RequestRejectedError
from data_plane.ingress import REGISTRY as INGRESS
from data_plane.policy import model_allowed
from data_plane.runtime import runtime_of

if TYPE_CHECKING:
    from starlette.requests import Request

    from contract import KeyEntry, ModelEntry
    from data_plane.bundle.holder import BundleSnapshot


class ModelInfoOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    context_window: int
    max_output_tokens: int | None
    input_modalities: list[Modality]
    output_modalities: list[Modality]
    capabilities: list[Capability]
    parameter_support: dict[str, ParameterSupport]


class ModelOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    object: Literal["model"] = "model"
    created: int
    owned_by: str
    gateway: ModelInfoOut


class ModelListOut(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    object: Literal["list"] = "list"
    data: list[ModelOut]


def _model_out(model: ModelEntry, snapshot: BundleSnapshot) -> ModelOut:
    return ModelOut(
        id=model.model_id,
        created=int(snapshot.bundle.issued_at.timestamp()),
        owned_by=model.provider_id,
        gateway=ModelInfoOut(
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            input_modalities=model.input_modalities,
            output_modalities=model.output_modalities,
            capabilities=model.capabilities,
            parameter_support=model.parameter_support,
        ),
    )


def _retrieve_model(model_id: str, key: KeyEntry, snapshot: BundleSnapshot) -> ModelOut:
    model = snapshot.model_index.get(model_id)
    if model is None or not model_allowed(model, key, snapshot):
        raise RequestRejectedError(404, "unknown_model")
    return _model_out(model, snapshot)


async def models(request: Request) -> Response:
    try:
        key, snapshot = authenticate_request(request, runtime_of(request).holder)
        if "model_id" in request.path_params:
            result = _retrieve_model(str(request.path_params["model_id"]), key, snapshot)
        else:
            result = ModelListOut(
                data=[
                    _model_out(model, snapshot)
                    for model in sorted(snapshot.model_index.values(), key=lambda model: model.model_id)
                    if model_allowed(model, key, snapshot)
                ]
            )
        response = Response(result.model_dump_json(), media_type="application/json")
    except RequestRejectedError as error:
        response = INGRESS["openai_native"].render_error(CanonicalError(status=error.status, code=error.code, message=error.message))
    response.headers["cache-control"] = "no-store"
    return response
