from __future__ import annotations

import json
import os
import time
from typing import Any

import psycopg2
import psycopg2.extras
import streamlit as st

from pst.helpers import utc_now

# Calculation types supported by sub-families
CALCULATION_TYPES = [
    "value_based",
    "equipment_equivalent",
    "cost_plus",
    "manual_wrp",
    "no_calculation",
]

CALCULATION_TYPE_LABELS = {
    "value_based": "Value Based (CT-1)",
    "equipment_equivalent": "Equipment Equivalent (CT-2)",
    "cost_plus": "Cost Price Plus (CT-3)",
    "manual_wrp": "Manual / Market WRP (CT-4)",
    "no_calculation": "No Calculation",
}

SUB_FAMILY_TYPES = ["Normal", "Strategic"]

_CALC_TYPE_FROM_LABEL = {
    "value based": "value_based",
    "equipment equivalent": "equipment_equivalent",
    "costprice plus": "cost_plus",
    "cost price plus": "cost_plus",
    "manual wrp": "manual_wrp",
    "no calculation": "no_calculation",
}

# 23 confirmed modalities from BRD Section 3.3
SEED_MODALITIES = [
    ("CC", "Connected Care"),
    ("CI", "Cardiology Informatics"),
    ("CT", "Computed Tomography Systems"),
    ("CV", "Cardio-Vascular Systems"),
    ("DCP", "Digital Pathology"),
    ("DXR", "Diagnostic X-Ray Systems"),
    ("EC", "Emergency Care"),
    ("EI", "Enterprise Imaging"),
    ("EPD", "EPD Solutions"),
    ("H2H", "Hospital to Home"),
    ("ICAP", "Imaging Clinical Applications & Platforms"),
    ("IGT-D", "IGT Devices"),
    ("MA", "Monitoring and Analytics"),
    ("MR", "Magnetic Resonance Systems"),
    ("MVS", "Multi-Vendor Service"),
    ("PCSUP", "Medical Consumables & Sensors Equipment"),
    ("PCVAL", "PC Value Segment Solutions"),
    ("PETCT", "Positron Emission and Computed Tomography Systems"),
    ("SERV", "Services"),
    ("SPECT", "Gamma Cameras"),
    ("SUR", "Mobile C-arm Systems"),
    ("TC", "Therapeutic Care"),
    ("US", "Ultrasound Systems"),
]


def calc_type_from_label(label: str) -> str:
    key = label.strip().lower()
    if key in CALCULATION_TYPES:
        return key
    return _CALC_TYPE_FROM_LABEL.get(key, "manual_wrp")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _get_db_url() -> str:
    try:
        return st.secrets["DATABASE_URL"]
    except Exception:
        url = os.environ.get("DATABASE_URL")
        if not url:
            raise RuntimeError("DATABASE_URL not set in st.secrets or environment")
        return url


def connect() -> psycopg2.extensions.connection:
    """Open a database connection, retrying brief network-policy failures."""
    attempts = 3
    for attempt in range(attempts):
        try:
            return psycopg2.connect(
                _get_db_url(),
                connect_timeout=10,
                cursor_factory=psycopg2.extras.RealDictCursor,
            )
        except psycopg2.OperationalError:
            if attempt == attempts - 1:
                raise
            time.sleep(attempt + 1)

    raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS config (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id             BIGSERIAL PRIMARY KEY,
    table_name     TEXT NOT NULL,
    record_id      TEXT NOT NULL,
    action         TEXT NOT NULL,
    old_value_json TEXT,
    new_value_json TEXT,
    user_name      TEXT,
    created_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS modalities (
    id         BIGSERIAL PRIMARY KEY,
    code       TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS families (
    id          BIGSERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sub_families (
    id               BIGSERIAL PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    family_id        BIGINT NOT NULL REFERENCES families(id),
    calculation_type TEXT NOT NULL DEFAULT 'manual_wrp'
                     CHECK(calculation_type IN
                        ('value_based','equipment_equivalent',
                         'cost_plus','manual_wrp','no_calculation')),
    sub_family_type  TEXT NOT NULL DEFAULT 'Normal'
                     CHECK(sub_family_type IN ('Normal','Strategic')),
    description      TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sub_family_modalities (
    id            BIGSERIAL PRIMARY KEY,
    sub_family_id BIGINT NOT NULL REFERENCES sub_families(id) ON DELETE CASCADE,
    modality_id   BIGINT NOT NULL REFERENCES modalities(id),
    UNIQUE(sub_family_id, modality_id)
);

CREATE TABLE IF NOT EXISTS profit_centers (
    id                    BIGSERIAL PRIMARY KEY,
    profit_center         TEXT NOT NULL UNIQUE,
    description           TEXT,
    modality_id           BIGINT REFERENCES modalities(id),
    default_sub_family_id BIGINT REFERENCES sub_families(id),
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS characteristics (
    id                  BIGSERIAL PRIMARY KEY,
    characteristic_code TEXT NOT NULL UNIQUE,
    description         TEXT,
    category            TEXT,
    sub_family_id       BIGINT REFERENCES sub_families(id),
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS product_hierarchies (
    id                    BIGSERIAL PRIMARY KEY,
    hierarchy_code        TEXT NOT NULL UNIQUE,
    hierarchy_description TEXT,
    sub_family_id         BIGINT NOT NULL REFERENCES sub_families(id),
    created_at            TEXT NOT NULL,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keywords (
    id            BIGSERIAL PRIMARY KEY,
    keyword       TEXT NOT NULL,
    sub_family_id BIGINT NOT NULL REFERENCES sub_families(id),
    priority      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
"""


def init_db() -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            for statement in _SCHEMA_SQL.strip().split(";"):
                statement = statement.strip()
                if statement:
                    cur.execute(statement)
        conn.commit()


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

def seed_modalities() -> int:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM modalities")
            if cur.fetchone()["cnt"] > 0:
                return 0
            now = utc_now()
            for code, name in SEED_MODALITIES:
                cur.execute(
                    "INSERT INTO modalities (code, name, created_at, updated_at) VALUES (%s,%s,%s,%s) ON CONFLICT (code) DO NOTHING",
                    (code, name, now, now),
                )
        conn.commit()
    return len(SEED_MODALITIES)


# ---------------------------------------------------------------------------
# Audit helpers
# ---------------------------------------------------------------------------

def add_audit(
    conn: psycopg2.extensions.connection,
    table_name: str,
    record_id: str,
    action: str,
    old_value: dict | None = None,
    new_value: dict | None = None,
    user_name: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO audit_log
               (table_name, record_id, action, old_value_json, new_value_json, user_name, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (
                table_name,
                str(record_id),
                action,
                json.dumps(old_value, sort_keys=True) if old_value else None,
                json.dumps(new_value, sort_keys=True) if new_value else None,
                user_name,
                utc_now(),
            ),
        )


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def get_config(key: str, default: str = "") -> str:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT value FROM config WHERE key = %s", (key,))
            row = cur.fetchone()
    return row["value"] if row else default


def set_config(key: str, value: str) -> None:
    now = utc_now()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO config (key, value, updated_at) VALUES (%s, %s, %s)
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = EXCLUDED.updated_at""",
                (key, value, now),
            )
        conn.commit()


# ---------------------------------------------------------------------------
# Dashboard statistics
# ---------------------------------------------------------------------------

_TABLE_NAMES = [
    "modalities",
    "families",
    "sub_families",
    "profit_centers",
    "characteristics",
    "product_hierarchies",
    "keywords",
]


def table_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    with connect() as conn:
        with conn.cursor() as cur:
            for table in _TABLE_NAMES:
                cur.execute(f"SELECT COUNT(*) AS cnt FROM {table}")  # noqa: S608
                row = cur.fetchone()
                counts[table] = row["cnt"] if row else 0
    return counts


def recent_audit(limit: int = 10) -> list[dict[str, Any]]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (limit,))
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Modalities
# ---------------------------------------------------------------------------

def list_modalities() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM modalities ORDER BY code")
            rows = cur.fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Families
# ---------------------------------------------------------------------------

def list_families() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM families ORDER BY name")
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_family(family_id: int) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM families WHERE id = %s", (family_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def upsert_family(code: str, name: str, description: str = "", family_id: int | None = None) -> int:
    now = utc_now()
    with connect() as conn:
        with conn.cursor() as cur:
            if family_id:
                cur.execute("SELECT * FROM families WHERE id = %s", (family_id,))
                old = dict(cur.fetchone())
                cur.execute(
                    "UPDATE families SET code=%s, name=%s, description=%s, updated_at=%s WHERE id=%s",
                    (code, name, description, now, family_id),
                )
                add_audit(conn, "families", str(family_id), "update",
                          old_value=old, new_value={"code": code, "name": name, "description": description})
                conn.commit()
                return family_id
            else:
                cur.execute(
                    "INSERT INTO families (code, name, description, created_at, updated_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                    (code, name, description, now, now),
                )
                new_id = cur.fetchone()["id"]
                add_audit(conn, "families", str(new_id), "insert",
                          new_value={"code": code, "name": name, "description": description})
                conn.commit()
                return new_id


def delete_family(family_id: int) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM sub_families WHERE family_id = %s", (family_id,))
            if cur.fetchone()["cnt"] > 0:
                return False
            cur.execute("SELECT * FROM families WHERE id = %s", (family_id,))
            old = cur.fetchone()
            if not old:
                return False
            cur.execute("DELETE FROM families WHERE id = %s", (family_id,))
            add_audit(conn, "families", str(family_id), "delete", old_value=dict(old))
        conn.commit()
    return True


# ---------------------------------------------------------------------------
# Sub-Families
# ---------------------------------------------------------------------------

def list_sub_families(family_id: int | None = None) -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            base = """SELECT sf.*, f.name AS family_name,
                             STRING_AGG(m.code, ', ' ORDER BY m.code) AS modality_codes
                      FROM sub_families sf
                      JOIN families f ON sf.family_id = f.id
                      LEFT JOIN sub_family_modalities sfm ON sfm.sub_family_id = sf.id
                      LEFT JOIN modalities m ON sfm.modality_id = m.id"""
            if family_id:
                cur.execute(
                    base + " WHERE sf.family_id = %s GROUP BY sf.id, f.name ORDER BY sf.name",
                    (family_id,),
                )
            else:
                cur.execute(base + " GROUP BY sf.id, f.name ORDER BY f.name, sf.name")
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_sub_family(sf_id: int) -> dict | None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM sub_families WHERE id = %s", (sf_id,))
            row = cur.fetchone()
    return dict(row) if row else None


def upsert_sub_family(
    code: str,
    name: str,
    family_id: int,
    calculation_type: str = "manual_wrp",
    sub_family_type: str = "Normal",
    description: str = "",
    sf_id: int | None = None,
) -> int:
    now = utc_now()
    with connect() as conn:
        with conn.cursor() as cur:
            if sf_id:
                cur.execute("SELECT * FROM sub_families WHERE id = %s", (sf_id,))
                old = dict(cur.fetchone())
                cur.execute(
                    """UPDATE sub_families
                       SET code=%s, name=%s, family_id=%s,
                           calculation_type=%s, sub_family_type=%s, description=%s, updated_at=%s
                       WHERE id=%s""",
                    (code, name, family_id, calculation_type, sub_family_type, description, now, sf_id),
                )
                add_audit(conn, "sub_families", str(sf_id), "update", old_value=old,
                          new_value={"code": code, "name": name, "calculation_type": calculation_type})
                conn.commit()
                return sf_id
            else:
                cur.execute(
                    """INSERT INTO sub_families
                       (code, name, family_id, calculation_type, sub_family_type, description, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (code, name, family_id, calculation_type, sub_family_type, description, now, now),
                )
                new_id = cur.fetchone()["id"]
                add_audit(conn, "sub_families", str(new_id), "insert",
                          new_value={"code": code, "name": name, "calculation_type": calculation_type})
                conn.commit()
                return new_id


def set_sub_family_modalities(sf_id: int, modality_ids: list[int]) -> None:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sub_family_modalities WHERE sub_family_id = %s", (sf_id,))
            for mid in modality_ids:
                cur.execute(
                    "INSERT INTO sub_family_modalities (sub_family_id, modality_id) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (sf_id, mid),
                )
        conn.commit()


def get_sub_family_modality_ids(sf_id: int) -> list[int]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT modality_id FROM sub_family_modalities WHERE sub_family_id = %s",
                (sf_id,),
            )
            rows = cur.fetchall()
    return [r["modality_id"] for r in rows]


def delete_sub_family(sf_id: int) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            for ref_table, ref_col in [
                ("profit_centers", "default_sub_family_id"),
                ("characteristics", "sub_family_id"),
                ("product_hierarchies", "sub_family_id"),
                ("keywords", "sub_family_id"),
            ]:
                cur.execute(
                    f"SELECT COUNT(*) AS cnt FROM {ref_table} WHERE {ref_col} = %s", (sf_id,)  # noqa: S608
                )
                if cur.fetchone()["cnt"] > 0:
                    return False
            cur.execute("SELECT * FROM sub_families WHERE id = %s", (sf_id,))
            old = cur.fetchone()
            if not old:
                return False
            cur.execute("DELETE FROM sub_families WHERE id = %s", (sf_id,))
            add_audit(conn, "sub_families", str(sf_id), "delete", old_value=dict(old))
        conn.commit()
    return True


# ---------------------------------------------------------------------------
# Profit Centers
# ---------------------------------------------------------------------------

def list_profit_centers() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT pc.*, sf.name AS sub_family_name, m.code AS modality_code
                   FROM profit_centers pc
                   LEFT JOIN sub_families sf ON pc.default_sub_family_id = sf.id
                   LEFT JOIN modalities m ON pc.modality_id = m.id
                   ORDER BY pc.profit_center"""
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def upsert_profit_center(
    profit_center: str,
    description: str = "",
    modality_id: int | None = None,
    default_sub_family_id: int | None = None,
    pc_id: int | None = None,
) -> int:
    now = utc_now()
    with connect() as conn:
        with conn.cursor() as cur:
            if pc_id:
                cur.execute("SELECT * FROM profit_centers WHERE id = %s", (pc_id,))
                old = dict(cur.fetchone())
                cur.execute(
                    """UPDATE profit_centers
                       SET profit_center=%s, description=%s, modality_id=%s,
                           default_sub_family_id=%s, updated_at=%s
                       WHERE id=%s""",
                    (profit_center, description, modality_id, default_sub_family_id, now, pc_id),
                )
                add_audit(conn, "profit_centers", str(pc_id), "update", old_value=old)
                conn.commit()
                return pc_id
            else:
                cur.execute(
                    """INSERT INTO profit_centers
                       (profit_center, description, modality_id, default_sub_family_id, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (profit_center, description, modality_id, default_sub_family_id, now, now),
                )
                new_id = cur.fetchone()["id"]
                add_audit(conn, "profit_centers", str(new_id), "insert",
                          new_value={"profit_center": profit_center})
                conn.commit()
                return new_id


def delete_profit_center(pc_id: int) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM profit_centers WHERE id = %s", (pc_id,))
            old = cur.fetchone()
            if not old:
                return False
            cur.execute("DELETE FROM profit_centers WHERE id = %s", (pc_id,))
            add_audit(conn, "profit_centers", str(pc_id), "delete", old_value=dict(old))
        conn.commit()
    return True


# ---------------------------------------------------------------------------
# Characteristics
# ---------------------------------------------------------------------------

def list_characteristics() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.*, sf.name AS sub_family_name
                   FROM characteristics c
                   LEFT JOIN sub_families sf ON c.sub_family_id = sf.id
                   ORDER BY c.characteristic_code"""
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def upsert_characteristic(
    characteristic_code: str,
    description: str = "",
    category: str = "",
    sub_family_id: int | None = None,
    char_id: int | None = None,
) -> int:
    now = utc_now()
    with connect() as conn:
        with conn.cursor() as cur:
            if char_id:
                cur.execute("SELECT * FROM characteristics WHERE id = %s", (char_id,))
                old = dict(cur.fetchone())
                cur.execute(
                    """UPDATE characteristics
                       SET characteristic_code=%s, description=%s, category=%s,
                           sub_family_id=%s, updated_at=%s
                       WHERE id=%s""",
                    (characteristic_code, description, category, sub_family_id, now, char_id),
                )
                add_audit(conn, "characteristics", str(char_id), "update", old_value=old)
                conn.commit()
                return char_id
            else:
                cur.execute(
                    """INSERT INTO characteristics
                       (characteristic_code, description, category, sub_family_id, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (characteristic_code, description, category, sub_family_id, now, now),
                )
                new_id = cur.fetchone()["id"]
                add_audit(conn, "characteristics", str(new_id), "insert",
                          new_value={"characteristic_code": characteristic_code})
                conn.commit()
                return new_id


def delete_characteristic(char_id: int) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM characteristics WHERE id = %s", (char_id,))
            old = cur.fetchone()
            if not old:
                return False
            cur.execute("DELETE FROM characteristics WHERE id = %s", (char_id,))
            add_audit(conn, "characteristics", str(char_id), "delete", old_value=dict(old))
        conn.commit()
    return True


# ---------------------------------------------------------------------------
# Product Hierarchies
# ---------------------------------------------------------------------------

def list_product_hierarchies() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT ph.*, sf.name AS sub_family_name
                   FROM product_hierarchies ph
                   JOIN sub_families sf ON ph.sub_family_id = sf.id
                   ORDER BY ph.hierarchy_code"""
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def upsert_product_hierarchy(
    hierarchy_code: str,
    hierarchy_description: str = "",
    sub_family_id: int = 0,
    ph_id: int | None = None,
) -> int:
    now = utc_now()
    with connect() as conn:
        with conn.cursor() as cur:
            if ph_id:
                cur.execute("SELECT * FROM product_hierarchies WHERE id = %s", (ph_id,))
                old = dict(cur.fetchone())
                cur.execute(
                    """UPDATE product_hierarchies
                       SET hierarchy_code=%s, hierarchy_description=%s,
                           sub_family_id=%s, updated_at=%s
                       WHERE id=%s""",
                    (hierarchy_code, hierarchy_description, sub_family_id, now, ph_id),
                )
                add_audit(conn, "product_hierarchies", str(ph_id), "update", old_value=old)
                conn.commit()
                return ph_id
            else:
                cur.execute(
                    """INSERT INTO product_hierarchies
                       (hierarchy_code, hierarchy_description, sub_family_id, created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s) RETURNING id""",
                    (hierarchy_code, hierarchy_description, sub_family_id, now, now),
                )
                new_id = cur.fetchone()["id"]
                add_audit(conn, "product_hierarchies", str(new_id), "insert",
                          new_value={"hierarchy_code": hierarchy_code})
                conn.commit()
                return new_id


def delete_product_hierarchy(ph_id: int) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM product_hierarchies WHERE id = %s", (ph_id,))
            old = cur.fetchone()
            if not old:
                return False
            cur.execute("DELETE FROM product_hierarchies WHERE id = %s", (ph_id,))
            add_audit(conn, "product_hierarchies", str(ph_id), "delete", old_value=dict(old))
        conn.commit()
    return True


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

def list_keywords() -> list[dict]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT k.*, sf.name AS sub_family_name
                   FROM keywords k
                   JOIN sub_families sf ON k.sub_family_id = sf.id
                   ORDER BY k.priority DESC, k.keyword"""
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def upsert_keyword(keyword: str, sub_family_id: int, priority: int = 0, kw_id: int | None = None) -> int:
    now = utc_now()
    with connect() as conn:
        with conn.cursor() as cur:
            if kw_id:
                cur.execute("SELECT * FROM keywords WHERE id = %s", (kw_id,))
                old = dict(cur.fetchone())
                cur.execute(
                    "UPDATE keywords SET keyword=%s, sub_family_id=%s, priority=%s, updated_at=%s WHERE id=%s",
                    (keyword, sub_family_id, priority, now, kw_id),
                )
                add_audit(conn, "keywords", str(kw_id), "update", old_value=old)
                conn.commit()
                return kw_id
            else:
                cur.execute(
                    "INSERT INTO keywords (keyword, sub_family_id, priority, created_at, updated_at) VALUES (%s,%s,%s,%s,%s) RETURNING id",
                    (keyword, sub_family_id, priority, now, now),
                )
                new_id = cur.fetchone()["id"]
                add_audit(conn, "keywords", str(new_id), "insert", new_value={"keyword": keyword})
                conn.commit()
                return new_id


def delete_keyword(kw_id: int) -> bool:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM keywords WHERE id = %s", (kw_id,))
            old = cur.fetchone()
            if not old:
                return False
            cur.execute("DELETE FROM keywords WHERE id = %s", (kw_id,))
            add_audit(conn, "keywords", str(kw_id), "delete", old_value=dict(old))
        conn.commit()
    return True
