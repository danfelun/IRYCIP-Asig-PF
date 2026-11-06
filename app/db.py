import os
import sqlite3
from datetime import datetime, timezone
from openpyxl import load_workbook
from flask import current_app, g
from .topics import TOPICS

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS students (
    email TEXT PRIMARY KEY COLLATE NOCASE,
    name TEXT NOT NULL,
    group_no INTEGER NOT NULL CHECK(group_no > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
);
CREATE TABLE IF NOT EXISTS topics (
    code TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    platform TEXT NOT NULL,
    protocols TEXT NOT NULL,
    network TEXT NOT NULL,
    summary TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS assignments (
    group_no INTEGER PRIMARY KEY CHECK(group_no > 0),
    topic_code TEXT NOT NULL,
    claimed_by_email TEXT NOT NULL,
    claimed_by_name TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    FOREIGN KEY(topic_code) REFERENCES topics(code),
    FOREIGN KEY(claimed_by_email) REFERENCES students(email)
);
"""


def connect_db(path):
    db = sqlite3.connect(path, timeout=30, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    return db


def get_db():
    if "db" not in g:
        g.db = connect_db(current_app.config["DATABASE"])
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _needs_schema_migration(db):
    students_sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='students'"
    ).fetchone()
    assignments_sql = db.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='assignments'"
    ).fetchone()
    if not students_sql or not assignments_sql:
        return False

    s_sql = (students_sql["sql"] or "").lower()
    a_sql = (assignments_sql["sql"] or "").lower()
    student_cols = {r["name"] for r in db.execute("PRAGMA table_info(students)").fetchall()}

    return (
        "active" not in student_cols
        or "between 1 and 12" in s_sql
        or "between 1 and 12" in a_sql
        or "topic_code text not null unique" in a_sql
    )


def _migrate_schema_if_needed(db):
    """Migra instalaciones v1 sin perder estudiantes ni asignaciones existentes."""
    if not _needs_schema_migration(db):
        return

    students_cols = {r["name"] for r in db.execute("PRAGMA table_info(students)").fetchall()}
    if "active" in students_cols:
        students = [dict(r) for r in db.execute(
            "SELECT email,name,group_no,active FROM students"
        ).fetchall()]
    else:
        students = [
            {**dict(r), "active": 1}
            for r in db.execute("SELECT email,name,group_no FROM students").fetchall()
        ]

    assignments = [dict(r) for r in db.execute(
        "SELECT group_no,topic_code,claimed_by_email,claimed_by_name,assigned_at FROM assignments"
    ).fetchall()]

    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("DROP TABLE assignments")
        db.execute("DROP TABLE students")
        db.execute("""
            CREATE TABLE students (
                email TEXT PRIMARY KEY COLLATE NOCASE,
                name TEXT NOT NULL,
                group_no INTEGER NOT NULL CHECK(group_no > 0),
                active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1))
            )
        """)
        db.execute("""
            CREATE TABLE assignments (
                group_no INTEGER PRIMARY KEY CHECK(group_no > 0),
                topic_code TEXT NOT NULL,
                claimed_by_email TEXT NOT NULL,
                claimed_by_name TEXT NOT NULL,
                assigned_at TEXT NOT NULL,
                FOREIGN KEY(topic_code) REFERENCES topics(code),
                FOREIGN KEY(claimed_by_email) REFERENCES students(email)
            )
        """)
        for s in students:
            db.execute(
                "INSERT INTO students(email,name,group_no,active) VALUES(?,?,?,?)",
                (s["email"], s["name"], s["group_no"], s.get("active", 1)),
            )
        for a in assignments:
            db.execute(
                """INSERT INTO assignments(group_no,topic_code,claimed_by_email,claimed_by_name,assigned_at)
                   VALUES(?,?,?,?,?)""",
                (a["group_no"], a["topic_code"], a["claimed_by_email"], a["claimed_by_name"], a["assigned_at"]),
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.execute("PRAGMA foreign_keys = ON")


def init_db(app):
    db = connect_db(app.config["DATABASE"])
    db.executescript(SCHEMA)
    _migrate_schema_if_needed(db)
    for t in TOPICS:
        db.execute(
            """INSERT INTO topics(code,title,platform,protocols,network,summary)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(code) DO UPDATE SET
                 title=excluded.title, platform=excluded.platform,
                 protocols=excluded.protocols, network=excluded.network,
                 summary=excluded.summary""",
            (t["code"], t["title"], t["platform"], t["protocols"], t["network"], t["summary"]),
        )
    db.close()
    app.teardown_appcontext(close_db)


def import_students_xlsx(path, db_path):
    """Sincroniza la matriz. Los registros ausentes quedan inactivos, no se eliminan."""
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    ws.reset_dimensions()
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("La matriz no contiene registros")

    header = [str(x).strip() if x is not None else "" for x in rows[0]]
    required = ["Nombre", "Correo Institucional", "Grupo"]
    if header[:3] != required:
        raise ValueError(f"Encabezados esperados: {required}; encontrados: {header[:3]}")

    records = []
    for row in rows[1:]:
        if not row or not row[1]:
            continue
        name = str(row[0]).strip()
        email = str(row[1]).strip().lower()
        group_no = int(row[2])
        if group_no <= 0:
            raise ValueError(f"Número de grupo inválido para {email}: {group_no}")
        records.append((email, name, group_no))

    if not records:
        raise ValueError("La matriz no contiene estudiantes válidos")

    db = connect_db(db_path)
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("UPDATE students SET active=0")
        for email, name, group_no in records:
            db.execute(
                """INSERT INTO students(email,name,group_no,active) VALUES(?,?,?,1)
                   ON CONFLICT(email) DO UPDATE SET
                     name=excluded.name,
                     group_no=excluded.group_no,
                     active=1""",
                (email, name, group_no),
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()
    return len(records)


def import_students_if_available(app):
    path = app.config.get("STUDENTS_XLSX")
    if not path or not os.path.exists(path):
        return 0
    return import_students_xlsx(path, app.config["DATABASE"])


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
