from __future__ import annotations

import json
import subprocess
import sys

FORBIDDEN = ["sqlalchemy", "sqlmodel", "asyncpg", "psycopg", "alembic", "fastapi", "control_plane"]

SCRIPT = """
import json
import sys
import data_plane.app
print(json.dumps(sorted(sys.modules)))
"""


def test_importing_data_plane_loads_no_forbidden_modules():
    result = subprocess.run([sys.executable, "-c", SCRIPT], capture_output=True, text=True, check=True)  # noqa: S603 sys.executable with a literal script
    loaded = json.loads(result.stdout)
    for name in FORBIDDEN:
        assert name not in loaded
