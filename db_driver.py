"""
Database driver shim that lets the Flask app use either SQLite (local/dev) or
Render PostgreSQL (production) without changing the SQL-heavy code in db.py.

Usage:
    import db_driver as sqlite3
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

If the environment variable DATABASE_URL (or DB_PATH) is a PostgreSQL URL,
psycopg2 is used.  Otherwise a normal SQLite file is opened.
"""

import os
import re
import sqlite3 as _sqlite3

# Keep the original Row class so db.py can set conn.row_factory = sqlite3.Row
Row = _sqlite3.Row

# Try to load psycopg2; if it is missing we fall back to SQLite only.
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    PSYCOPG2_AVAILABLE = True
except ImportError:  # pragma: no cover
    psycopg2 = None
    RealDictCursor = None
    PSYCOPG2_AVAILABLE = False


# A single IntegrityError that app.py can catch regardless of backend.
if PSYCOPG2_AVAILABLE:
    IntegrityError = (_sqlite3.IntegrityError, psycopg2.IntegrityError)
else:
    IntegrityError = _sqlite3.IntegrityError


_POSTGRES_NOW = "to_char(now(), 'YYYY-MM-DD\"T\"HH24:MI:SS.US')"


def _is_postgres_dsn(dsn):
    return isinstance(dsn, str) and dsn.startswith(("postgres://", "postgresql://"))


def _normalize_postgres_dsn(dsn):
    if dsn.startswith("postgres://"):
        return "postgresql://" + dsn[len("postgres://"):]
    return dsn


def connect(database=None, *args, **kwargs):
    """Open a database connection."""
    if database is None:
        database = (
            os.environ.get("DATABASE_URL")
            or os.environ.get("DB_PATH")
            or "app.db"
        )
    if _is_postgres_dsn(database):
        if not PSYCOPG2_AVAILABLE:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg2/psycopg2-binary is not installed"
            )
        return PostgresConnection(_normalize_postgres_dsn(database))
    return SQLiteConnection(database, *args, **kwargs)


class SQLiteConnection:
    """Thin wrapper around the standard sqlite3 connection."""

    def __init__(self, database, *args, **kwargs):
        self._conn = _sqlite3.connect(database, *args, **kwargs)
        self._conn.row_factory = _sqlite3.Row

    @property
    def row_factory(self):
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._conn.row_factory = value

    def execute(self, sql, params=None):
        if params is None:
            return self._conn.execute(sql)
        return self._conn.execute(sql, params)

    def executescript(self, sql):
        return self._conn.executescript(sql)

    def __getattr__(self, name):
        return getattr(self._conn, name)


class PostgresConnection:
    """psycopg2 connection that speaks the sqlite3 API used by db.py."""

    def __init__(self, dsn):
        self._dsn = dsn
        self._conn = psycopg2.connect(dsn, cursor_factory=RealDictCursor)

    # db.py assigns conn.row_factory = sqlite3.Row; just ignore it for Postgres.
    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, value):
        pass

    def execute(self, sql, params=None):
        if params is None:
            params = ()
        processed = _preprocess_postgres(sql)
        if processed is None:
            return _DummyCursor()
        cur = self._conn.cursor()
        try:
            cur.execute(processed, params)
        except Exception:
            self._conn.rollback()
            raise
        return PostgresCursor(cur)

    def executescript(self, sql):
        for stmt in _split_sql(sql):
            stmt = stmt.strip()
            if stmt:
                self.execute(stmt)
        return self

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()

    def rollback(self):
        self._conn.rollback()


class PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    @property
    def rowcount(self):
        return self._cursor.rowcount


class _DummyCursor:
    """Cursor returned for no-op PRAGMA statements on PostgreSQL."""

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    @property
    def rowcount(self):
        return 0


def _preprocess_postgres(sql):
    """Translate SQLite-flavoured SQL used in db.py into PostgreSQL SQL."""
    original = sql.strip()
    if not original:
        return original

    # PRAGMA table_info(table) -> Postgres column listing
    m = re.match(
        r"PRAGMA\s+table_info\s*\(\s*([^\s)]+)\s*\)\s*;?$",
        original,
        re.IGNORECASE,
    )
    if m:
        table = m.group(1).strip("\"'\"")
        return (
            "SELECT column_name as name FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND table_schema = current_schema()"
        )

    # PRAGMA foreign_keys / journal_mode are SQLite-only; skip them.
    if re.match(r"PRAGMA\s+(foreign_keys|journal_mode)\s*=", original, re.IGNORECASE):
        return None

    # INSERT OR IGNORE is a SQLite extension.
    if re.match(r"INSERT\s+OR\s+IGNORE\s+INTO", original, re.IGNORECASE):
        sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", original, count=1, flags=re.IGNORECASE)
        sql = sql.rstrip(";")
        sql += " ON CONFLICT DO NOTHING"
    else:
        sql = original

    # SQLite datetime('now') -> a TEXT value compatible with Python isoformat().
    sql = _replace_datetime_now(sql)

    # Convert ? placeholders to PostgreSQL %s placeholders.
    sql = _replace_placeholders(sql)

    return sql


def _replace_datetime_now(sql):
    """Replace datetime('now') / datetime("now") with a Postgres TEXT timestamp."""
    out = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            # Copy string literal verbatim, handling doubled quotes.
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                out.append(sql[i])
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        out.append(sql[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        # Look for datetime('now') or datetime("now")
        match = re.match(r"datetime\(['\"]now['\"]\)", sql[i:], re.IGNORECASE)
        if match:
            out.append(_POSTGRES_NOW)
            i += match.end()
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _replace_placeholders(sql):
    """Replace ? placeholders with %s, ignoring those inside string literals."""
    out = []
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                out.append(sql[i])
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        out.append(sql[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == "?":
            out.append("%s")
        elif ch == "%":
            # Escape literal % for psycopg2 unless it is already a placeholder %s.
            if i + 1 < n and sql[i + 1] == "s":
                out.append(ch)
            else:
                out.append("%%")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def _split_sql(script):
    """Split a SQL script on semicolons, respecting string literals."""
    statements = []
    current = []
    i = 0
    n = len(script)
    while i < n:
        ch = script[i]
        if ch in ("'", '"'):
            quote = ch
            current.append(ch)
            i += 1
            while i < n:
                current.append(script[i])
                if script[i] == quote:
                    if i + 1 < n and script[i + 1] == quote:
                        current.append(script[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        if ch == ";":
            statements.append("".join(current))
            current = []
            i += 1
            continue
        current.append(ch)
        i += 1
    if current:
        statements.append("".join(current))
    return statements
