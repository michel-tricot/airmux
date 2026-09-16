from __future__ import annotations

import pytest
from sqlalchemy import Index
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from control_plane.models.common import KeyColumn, Keyset


class Base(DeclarativeBase):
    pass


class IndexedItem(Base):
    __tablename__ = "pagination_indexed_item"
    __table_args__ = (Index("pagination_indexed_item_org_id_id_idx", "org_id", "id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int]


class UnindexedItem(Base):
    __tablename__ = "pagination_unindexed_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int]


def test_keyset_requires_a_covering_index():
    keyset = Keyset(
        model=IndexedItem,
        filter_columns=("org_id",),
        columns=(KeyColumn(IndexedItem.id, "asc", "int"),),
    )

    assert keyset.model is IndexedItem

    with pytest.raises(ValueError, match="pagination index"):
        Keyset(
            model=UnindexedItem,
            filter_columns=("org_id",),
            columns=(KeyColumn(UnindexedItem.id, "asc", "int"),),
        )
