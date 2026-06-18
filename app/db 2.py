"""
Dragon Technologies Inventory Manager - Database layer
SQLite schema, connection helper, and first-run seeding.
"""
import sqlite3
import os
from datetime import datetime

# Where the SQLite database lives.
#
#   * Home / Docker: the compose file sets INVENTORY_DB_PATH=/data/inventory.db
#     so the database lands in the mounted volume and survives rebuilds.
#   * Work / run-from-source: no env var is set, so it falls back to a local
#     "data/inventory.db" next to the app. This means `python3 app.py` just
#     works with nothing to remember.
#
# This mirrors the env-var-with-local-fallback pattern CLOCKIN already uses,
# so both modules behave identically: `python3 app.py` at work, /data volume
# at home. The INVENTORY_ prefix keeps these vars from colliding with
# CLOCKIN's CLOCKIN_ prefixed vars if both apps share a machine.
_DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "data", "inventory.db")
DB_PATH = os.environ.get("INVENTORY_DB_PATH", _DEFAULT_DB)


def get_db():
    """Open a connection with row access by column name and FK enforcement on."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SCHEMA = """
-- Application users: teacher (admin), student stockroom staff (manager),
-- and ordinary students. Passwords are bcrypt-hashed.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('admin','manager','student')),
    created_at    TEXT NOT NULL
);

-- Students who can have items checked out to them. Keyed by employee_id,
-- which is the SHARED KEY with the CLOCKIN app. The physical CLOCKIN badge
-- is the integration: scanning it yields this employee_id.
CREATE TABLE IF NOT EXISTS students (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id   TEXT UNIQUE NOT NULL,   -- e.g. ITF-001, CYB1-003  (from CLOCKIN)
    name          TEXT NOT NULL,
    student_id    TEXT,                   -- official school ID, optional
    section       TEXT,                   -- e.g. CYB1, ITF
    active        INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL
);

-- Categories define the ID prefix and an optional per-category checkout cap.
CREATE TABLE IF NOT EXISTS categories (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT UNIQUE NOT NULL,
    prefix        TEXT UNIQUE NOT NULL,   -- 2-4 letters, e.g. LAP, CMP
    checkout_limit INTEGER,               -- NULL = unlimited; assets only
    next_number   INTEGER NOT NULL DEFAULT 1
);

-- Items: both Assets (kind='asset') and Consumables (kind='consumable').
-- Phase 1 uses assets; consumable columns are present for Phase 2.
CREATE TABLE IF NOT EXISTS items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    item_code           TEXT UNIQUE NOT NULL,   -- e.g. DT-LAP-014
    name                TEXT NOT NULL,
    kind                TEXT NOT NULL CHECK (kind IN ('asset','consumable')),
    category_id         INTEGER NOT NULL REFERENCES categories(id),
    status              TEXT CHECK (status IN
                          ('Available','Checked Out','In Repair','Retired-Lost')),
    location            TEXT,
    notes               TEXT,
    quantity_on_hand    INTEGER,            -- consumables only (Phase 2)
    low_stock_threshold INTEGER,            -- consumables only (Phase 2)
    created_at          TEXT NOT NULL
);

-- One row per checkout event. return_at NULL means still out.
CREATE TABLE IF NOT EXISTS checkouts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id     INTEGER NOT NULL REFERENCES items(id),
    student_id  INTEGER NOT NULL REFERENCES students(id),
    checkout_at TEXT NOT NULL,
    due_at      TEXT NOT NULL,
    return_at   TEXT
);
"""


def init_db():
    """Create tables if missing and seed first-run data."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_db()
    conn.executescript(SCHEMA)
    conn.commit()
    _seed(conn)
    conn.close()


def _seed(conn):
    """Seed the default categories only.

    No admin account and no demo students are seeded: the first admin is
    created through the first-run /setup screen (see app.py), so no default
    password ever exists in the codebase. The app starts as a clean,
    production-ready slate.
    """
    now = datetime.now().isoformat(timespec="seconds")

    # --- Categories -------------------------------------------------------
    # These are sensible starting categories, not credentials, so seeding
    # them is fine. Admins can edit or add more later.
    if conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
        seed_categories = [
            ("Laptops", "LAP", 1),     # cap 1 laptop per student
            ("Tools", "TOOL", None),
            ("Components", "CMP", None),
            ("Peripherals", "PER", None),
            ("Cables", "CBL", None),
        ]
        for name, prefix, limit in seed_categories:
            conn.execute(
                "INSERT INTO categories (name, prefix, checkout_limit, next_number)"
                " VALUES (?, ?, ?, 1)",
                (name, prefix, limit),
            )

    conn.commit()


if __name__ == "__main__":
    init_db()
    print(f"Database initialised at {DB_PATH}")
