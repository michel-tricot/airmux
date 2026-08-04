from __future__ import annotations

from cli.common import test_app


@test_app.command()
def verify() -> None:
    """Run the acceptance checks against a running gateway. Not implemented yet."""
    raise NotImplementedError


@test_app.command()
def loadgen() -> None:
    """Generate request load against the data plane. Not implemented yet."""
    raise NotImplementedError
