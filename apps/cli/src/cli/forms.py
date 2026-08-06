from __future__ import annotations

import inspect
import sys
from types import UnionType
from typing import TYPE_CHECKING, Union, get_args, get_origin

import typer
from pydantic import BaseModel, ValidationError

from cli.client import org_client, payload, post_expecting
from cli.common import console

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx
    from pydantic.fields import FieldInfo


def _base_annotation(ann: object) -> object:
    if get_origin(ann) in (UnionType, Union):
        args = [a for a in get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0]
    return ann


def _is_list_field(field: FieldInfo) -> bool:
    return get_origin(_base_annotation(field.annotation)) is list


_FLAG_TYPES: dict[object, object] = {str: str | None, float: float | None, int: int | None}


def _flag_annotation(field: FieldInfo) -> object:
    base = _base_annotation(field.annotation)
    if get_origin(base) is list:
        return list[str] | None
    return _FLAG_TYPES.get(base, str | None)


def fill_spec[M: BaseModel](spec_cls: type[M], provided: dict) -> M:
    """Flags win; anything missing is prompted for, with the field description as the prompt."""
    values = {k: v for k, v in provided.items() if v not in (None, [], ())}
    for name, field in spec_cls.model_fields.items():
        if name in values:
            continue
        has_default = not field.is_required()
        if not sys.stdin.isatty():
            if has_default:
                continue
            console.print(f"[red]missing --{name.replace('_', '-')} and no terminal to prompt for it[/red]")
            raise typer.Exit(1)
        label = field.description or name.replace("_", " ")
        default = field.get_default(call_default_factory=True) if has_default else None
        raw = typer.prompt(label, default=",".join(default) if isinstance(default, list) else default)
        values[name] = [part.strip() for part in str(raw).split(",") if part.strip()] if _is_list_field(field) else raw
    try:
        return spec_cls.model_validate(values)
    except ValidationError as e:
        for err in e.errors():
            console.print(f"[red]{'.'.join(str(x) for x in err['loc'])}: {err['msg']}[/red]")
        raise typer.Exit(1) from e


def register_create(  # noqa: PLR0913, PLR0917 the six registration facts are the command's interface
    sub_app: typer.Typer,
    spec_cls: type[BaseModel],
    path: str,
    help_text: str,
    done: Callable[[dict], None],
    client: Callable[[str], httpx.Client] = org_client,
) -> None:
    """Derive a create command from a spec model: one flag and one prompt per field, never hardcoded."""

    def run(**kwargs: object) -> None:
        control_plane_url = str(kwargs.pop("control_plane_url", "") or "")
        spec = fill_spec(spec_cls, kwargs)
        with client(control_plane_url) as c:
            resp = post_expecting(c, path, spec.model_dump(mode="json"), ok=(200,))
        done(payload(resp))

    params = [
        inspect.Parameter(
            name,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            default=typer.Option(None, help=field.description),
            annotation=_flag_annotation(field),
        )
        for name, field in spec_cls.model_fields.items()
    ]
    params.append(inspect.Parameter("control_plane_url", inspect.Parameter.POSITIONAL_OR_KEYWORD, default=typer.Option(""), annotation=str))
    setattr(run, "__signature__", inspect.Signature(params))  # noqa: B010 typer reads the dynamic signature
    run.__doc__ = help_text
    sub_app.command("create")(run)
