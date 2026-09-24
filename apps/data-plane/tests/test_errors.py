from __future__ import annotations

import pytest
from pydantic import ValidationError

from data_plane.canonical import CanonicalError, GatewayErrorCode, ProviderErrorCode
from data_plane.errors import RequestRejectedError


def test_gateway_error_codes_are_closed():
    with pytest.raises(ValueError, match="invented"):
        GatewayErrorCode("invented")

    rejection = RequestRejectedError(404, GatewayErrorCode.unknown_model)
    assert rejection.code is GatewayErrorCode.unknown_model


def test_provider_error_codes_are_open_but_bounded():
    error = CanonicalError(status=502, code=ProviderErrorCode("provider_code"), message="failed")
    assert error.code == "provider_code"
    with pytest.raises(ValidationError):
        CanonicalError(status=502, code="x" * 129, message="failed")
