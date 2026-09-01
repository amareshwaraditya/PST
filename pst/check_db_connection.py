"""Safely verify a configured PostgreSQL connection without printing its URL."""

import sys
from pathlib import Path

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from pst.db import connect


if __name__ == "__main__":
    with connect() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)
    print("Database connectivity and authentication succeeded.")
