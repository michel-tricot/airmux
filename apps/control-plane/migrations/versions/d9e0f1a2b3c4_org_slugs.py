"""organization slugs

Revision ID: d9e0f1a2b3c4
Revises: d1e2f3a4b5c6
Create Date: 2026-08-17
"""

from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "d9e0f1a2b3c4"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None

SLUG_MAX_LENGTH = 63
DERIVED_SLUG_FALLBACK = "organization"


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:SLUG_MAX_LENGTH].strip("-")


def _free_slug(name: str, taken: set[str]) -> str:
    base = _slugify(name) or DERIVED_SLUG_FALLBACK
    if base not in taken:
        return base
    stem = base[: SLUG_MAX_LENGTH - 5].rstrip("-") or DERIVED_SLUG_FALLBACK
    suffix = 2
    while f"{stem}-{suffix}" in taken:
        suffix += 1
    return f"{stem}-{suffix}"


def upgrade() -> None:
    op.add_column("org", sa.Column("slug", postgresql.CITEXT(), nullable=True))
    connection = op.get_bind()
    connection.execute(sa.text("SELECT set_config('app.user_id', 'migration:d9e0f1a2b3c4', true)"))
    organizations = connection.execute(sa.text('SELECT id, name FROM "org" ORDER BY id')).mappings()
    taken: set[str] = set()
    for organization in organizations:
        slug = _free_slug(organization["name"], taken)
        connection.execute(sa.text('UPDATE "org" SET slug = :slug WHERE id = :id'), {"id": organization["id"], "slug": slug})
        taken.add(slug)
    op.alter_column("org", "slug", existing_type=postgresql.CITEXT(), nullable=False)
    op.create_unique_constraint("org_slug_key", "org", ["slug"])


def downgrade() -> None:
    op.drop_constraint("org_slug_key", "org", type_="unique")
    op.drop_column("org", "slug")
