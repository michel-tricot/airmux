from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import Table, inspect

from control_plane.models.common.base import Record

if TYPE_CHECKING:
    from collections.abc import Callable

type BundleInputScope = Literal["global", "org", "nullable_org"]


@dataclass(frozen=True)
class BundleInput:
    model: type[Record]
    scope: BundleInputScope
    columns: tuple[str, ...]


_BUNDLE_INPUTS: dict[type[Record], BundleInput] = {}


def bundle_input[T: Record](*, scope: BundleInputScope, columns: tuple[str, ...]) -> Callable[[type[T]], type[T]]:
    def register(cls: type[T]) -> type[T]:
        _BUNDLE_INPUTS[cls] = BundleInput(model=cls, scope=scope, columns=columns)
        return cls

    return register


def bundle_input_trigger_ddl_v1(table: str, scope: BundleInputScope, columns: tuple[str, ...]) -> tuple[str, str]:
    function = (
        "CREATE OR REPLACE FUNCTION mark_bundle_stale_v1() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "DECLARE position integer; changed boolean := false; old_org uuid; new_org uuid; BEGIN "
        "IF TG_OP = 'UPDATE' THEN FOR position IN 1..TG_NARGS - 1 LOOP "
        "IF to_jsonb(OLD) -> TG_ARGV[position] IS DISTINCT FROM to_jsonb(NEW) -> TG_ARGV[position] THEN changed := true; EXIT; END IF; "
        "END LOOP; IF NOT changed THEN RETURN NULL; END IF; END IF; "
        "IF TG_ARGV[0] = 'global' THEN "
        "INSERT INTO global_bundle_state (id, desired_generation) VALUES (1, 1) ON CONFLICT (id) DO UPDATE "
        "SET desired_generation = global_bundle_state.desired_generation + 1; RETURN NULL; END IF; "
        "IF TG_OP <> 'INSERT' THEN old_org := NULLIF(to_jsonb(OLD) ->> 'org_id', '')::uuid; END IF; "
        "IF TG_OP <> 'DELETE' THEN new_org := NULLIF(to_jsonb(NEW) ->> 'org_id', '')::uuid; END IF; "
        "IF TG_ARGV[0] = 'nullable_org' AND ((TG_OP <> 'INSERT' AND old_org IS NULL) OR (TG_OP <> 'DELETE' AND new_org IS NULL)) THEN "
        "INSERT INTO global_bundle_state (id, desired_generation) VALUES (1, 1) ON CONFLICT (id) DO UPDATE "
        "SET desired_generation = global_bundle_state.desired_generation + 1; END IF; "
        "IF old_org IS NOT NULL THEN INSERT INTO bundle_state "
        "(org_id, desired_generation, published_global_generation, published_org_generation, failure_count) "
        "SELECT old_org, 1, -1, -1, 0 WHERE EXISTS (SELECT 1 FROM org WHERE id = old_org) ON CONFLICT (org_id) DO UPDATE "
        "SET desired_generation = bundle_state.desired_generation + 1; END IF; "
        "IF new_org IS NOT NULL AND new_org IS DISTINCT FROM old_org THEN INSERT INTO bundle_state "
        "(org_id, desired_generation, published_global_generation, published_org_generation, failure_count) "
        "SELECT new_org, 1, -1, -1, 0 WHERE EXISTS (SELECT 1 FROM org WHERE id = new_org) ON CONFLICT (org_id) DO UPDATE "
        "SET desired_generation = bundle_state.desired_generation + 1; END IF; RETURN NULL; END $$"
    )
    arguments = ", ".join(f"'{value}'" for value in (scope, *columns))
    trigger = (
        f'CREATE OR REPLACE TRIGGER {table}_bundle_stale AFTER INSERT OR UPDATE OR DELETE ON "{table}" '
        f"FOR EACH ROW EXECUTE FUNCTION mark_bundle_stale_v1({arguments})"
    )
    return function, trigger


def bundle_input_trigger_drop_ddl_v1(table: str) -> tuple[str, str]:
    drop_trigger = f'DROP TRIGGER IF EXISTS {table}_bundle_stale ON "{table}"'
    drop_function = (
        "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_trigger t JOIN pg_proc p ON t.tgfoid = p.oid "
        "WHERE p.proname = 'mark_bundle_stale_v1' AND NOT t.tgisinternal) "
        "THEN DROP FUNCTION IF EXISTS mark_bundle_stale_v1(); END IF; END $$"
    )
    return drop_trigger, drop_function


def bundle_input_tables() -> list[tuple[Table, BundleInput]]:
    return sorted(
        (
            (table, bundle_input)
            for bundle_input in _BUNDLE_INPUTS.values()
            if (mapper := inspect(bundle_input.model, raiseerr=False)) is not None
            if isinstance(table := mapper.persist_selectable, Table)
        ),
        key=lambda entry: entry[0].name,
    )
