from __future__ import annotations

import pytest
from pg import db_name_for, drop_database


@pytest.fixture(autouse=True)
def _test_database(tmp_path):
    yield
    drop_database(db_name_for(tmp_path))
