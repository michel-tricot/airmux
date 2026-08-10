"""Backfill workspace slugs for databases created before the consolidated schema.

Revision ID: b4e7c2a91f06
Revises: a9f3c6e1d8b4
"""

from __future__ import annotations

from alembic import op

revision = "b4e7c2a91f06"
down_revision = "a9f3c6e1d8b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The consolidated initial revision already contains this column. Older
    # development databases stamped at that revision do not, so add it only
    # when the table predates the consolidation.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workspace'
                  AND column_name = 'slug'
            ) THEN
                ALTER TABLE workspace ADD COLUMN slug varchar;
            END IF;
        END
        $$;
        """
    )

    # Workspace writes are audited. Attribute this one-time schema backfill
    # to the system actor used by the existing fixture and taxonomy commands.
    op.execute("SELECT set_config('app.user_id', 'root', true)")

    # Existing names are the only source available for legacy rows. Keep the
    # same slug rules as the application and add a numeric suffix on collisions
    # within an organization.
    op.execute(
        """
        DO $$
        DECLARE
            workspace_row RECORD;
            base_slug text;
            candidate_slug text;
            suffix integer;
        BEGIN
            FOR workspace_row IN
                SELECT id, org_id, name
                FROM workspace
                WHERE slug IS NULL OR slug = ''
                ORDER BY org_id, id
            LOOP
                base_slug := trim(
                    BOTH '-' FROM left(
                        regexp_replace(lower(workspace_row.name), '[^a-z0-9]+', '-', 'g'),
                        63
                    )
                );
                IF base_slug = '' THEN
                    base_slug := 'workspace';
                END IF;

                candidate_slug := base_slug;
                suffix := 2;
                WHILE EXISTS (
                    SELECT 1
                    FROM workspace
                    WHERE org_id = workspace_row.org_id
                      AND slug = candidate_slug
                      AND id <> workspace_row.id
                ) LOOP
                    candidate_slug := left(base_slug, 57) || '-' || suffix::text;
                    suffix := suffix + 1;
                END LOOP;

                UPDATE workspace
                SET slug = candidate_slug
                WHERE id = workspace_row.id;
            END LOOP;
        END
        $$;
        """
    )

    op.execute("ALTER TABLE workspace ALTER COLUMN slug SET NOT NULL")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'workspace_org_id_slug_key'
            ) THEN
                ALTER TABLE workspace
                ADD CONSTRAINT workspace_org_id_slug_key UNIQUE (org_id, slug);
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'workspace_org_id_slug_key'
            ) THEN
                ALTER TABLE workspace DROP CONSTRAINT workspace_org_id_slug_key;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'workspace'
                  AND column_name = 'slug'
            ) THEN
                ALTER TABLE workspace DROP COLUMN slug;
            END IF;
        END
        $$;
        """
    )