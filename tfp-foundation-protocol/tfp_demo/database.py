# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Database abstraction layer supporting SQLite and PostgreSQL backends.

Enables horizontal scaling with multiple uvicorn workers:
- SQLite: Single-worker only (with WAL mode for better concurrency)
- PostgreSQL: Multi-worker safe with connection pooling

Usage:
    from tfp_demo.database import Database
    
    # SQLite (default, single-worker)
    db = Database.from_url("sqlite:///path/to/db.sqlite")
    
    # PostgreSQL (multi-worker)
    db = Database.from_url("postgresql://user:pass@host/db")
    
    with db.transaction() as conn:
        conn.execute("INSERT ...", params)
"""

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, List, Optional, Tuple, Union

log = logging.getLogger(__name__)

# Optional PostgreSQL support
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    _POSTGRES_AVAILABLE = True
except ImportError:  # pragma: no cover
    _POSTGRES_AVAILABLE = False
    psycopg2 = None  # type: ignore[misc]
    RealDictCursor = None  # type: ignore[misc]


class DatabaseError(Exception):
    """Raised for database-related errors."""


class Database:
    """
    Database abstraction supporting SQLite and PostgreSQL.

    Provides unified interface for:
    - Connection management
    - Transaction handling
    - Query execution (execute, fetchone, fetchall)
    - Schema initialization

    Thread-safe for SQLite (uses RLock).
    PostgreSQL relies on database-level concurrency.
    """

    def __init__(
        self,
        connection: Union[sqlite3.Connection, Any],
        db_type: str,
        lock: Optional[threading.RLock] = None,
    ):
        self._conn = connection
        self._db_type = db_type
        self._lock = lock
        self._pool = None

        if db_type == "sqlite":
            self._init_sqlite()
        elif db_type == "postgresql":
            self._init_postgresql()

    def _init_sqlite(self) -> None:
        """Configure SQLite connection."""
        # Enable WAL mode for better concurrent read performance
        if hasattr(self._conn, "execute"):
            try:
                # Check if in-memory database
                cursor = self._conn.execute("PRAGMA journal_mode")
                current_mode = cursor.fetchone()[0]
                if current_mode != "wal":
                    self._conn.execute("PRAGMA journal_mode=WAL")
                    log.info("SQLite WAL mode enabled")
            except Exception as exc:
                log.debug("Could not enable WAL mode (may be :memory:): %s", exc)

    def _init_postgresql(self) -> None:
        """PostgreSQL uses server-side concurrency control."""
        log.info("PostgreSQL connection established")

    @classmethod
    def from_url(cls, url: str) -> "Database":
        """
        Create Database instance from connection URL.

        Supports:
        - sqlite:///path/to/db.sqlite
        - sqlite:///:memory:
        - postgresql://user:pass@host:port/db
        """
        if url.startswith("sqlite://"):
            return cls._create_sqlite(url)
        elif url.startswith("postgresql://"):
            return cls._create_postgresql(url)
        elif url.startswith("postgres://"):
            # Handle postgres:// shorthand
            return cls._create_postgresql(url.replace("postgres://", "postgresql://", 1))
        else:
            # Default to SQLite for backward compatibility
            return cls._create_sqlite(f"sqlite:///{url}")

    @classmethod
    def _create_sqlite(cls, url: str) -> "Database":
        """Create SQLite database connection."""
        # Extract path from sqlite:///path
        path = url.replace("sqlite://", "")
        if path.startswith("/"):
            path = path[1:]

        if path == ":memory:":
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            log.info("SQLite :memory: database created")
        else:
            # Resolve to absolute path to prevent path traversal
            db_path = Path(path).resolve()
            # Ensure directory exists
            db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            log.info("SQLite database: %s", db_path)

        conn.row_factory = sqlite3.Row
        lock = threading.RLock()
        return cls(conn, "sqlite", lock=lock)

    @classmethod
    def _create_postgresql(cls, url: str) -> "Database":
        """Create PostgreSQL database connection."""
        if not _POSTGRES_AVAILABLE:
            raise DatabaseError(
                "PostgreSQL support requires psycopg2. "
                "Install: pip install psycopg2-binary"
            )

        conn = psycopg2.connect(url)
        conn.autocommit = False
        return cls(conn, "postgresql", dsn=url)

    @property
    def db_type(self) -> str:
        """Return database type: 'sqlite' or 'postgresql'."""
        return self._db_type

    @property
    def is_sqlite(self) -> bool:
        """True if using SQLite backend."""
        return self._db_type == "sqlite"

    @property
    def is_postgresql(self) -> bool:
        """True if using PostgreSQL backend."""
        return self._db_type == "postgresql"

    @property
    def supports_multiple_workers(self) -> bool:
        """True if database supports concurrent writes from multiple processes."""
        return self._db_type == "postgresql"

    @contextmanager
    def transaction(self) -> Generator[Any, None, None]:
        """
        Context manager for database transactions.

        For SQLite: acquires thread lock
        For PostgreSQL: uses database transactions

        Usage:
            with db.transaction() as conn:
                conn.execute("INSERT ...", params)
                # Auto-committed on success, rolled back on exception
        """
        if self._db_type == "sqlite":
            if self._lock:
                self._lock.acquire()
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                if self._lock:
                    self._lock.release()
        else:
            # PostgreSQL
            cursor = self._conn.cursor()
            try:
                yield cursor
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            finally:
                cursor.close()

    def execute(
        self, sql: str, parameters: Optional[Tuple[Any, ...]] = None
    ) -> Any:
        """Execute SQL statement."""
        with self.transaction() as conn:
            if self._db_type == "sqlite":
                return conn.execute(sql, parameters or ())
            else:
                conn.execute(sql, parameters or ())
                return conn

    def fetchone(
        self, sql: str, parameters: Optional[Tuple[Any, ...]] = None
    ) -> Optional[Any]:
        """Execute query and return single row."""
        if self._db_type == "sqlite":
            if self._lock:
                self._lock.acquire()
            try:
                cursor = self._conn.execute(sql, parameters or ())
                return cursor.fetchone()
            finally:
                if self._lock:
                    self._lock.release()
        else:
            # PostgreSQL: use transaction for consistency
            with self.transaction() as cursor:
                cursor.execute(sql, parameters or ())
                return cursor.fetchone()

    def fetchall(
        self, sql: str, parameters: Optional[Tuple[Any, ...]] = None
    ) -> List[Any]:
        """Execute query and return all rows."""
        if self._db_type == "sqlite":
            if self._lock:
                self._lock.acquire()
            try:
                cursor = self._conn.execute(sql, parameters or ())
                return cursor.fetchall()
            finally:
                if self._lock:
                    self._lock.release()
        else:
            # PostgreSQL: use transaction for consistency
            with self.transaction() as cursor:
                cursor.execute(sql, parameters or ())
                return cursor.fetchall()

    def executescript(self, sql: str) -> None:
        """Execute SQL script (multiple statements). SQLite only."""
        if self._db_type == "sqlite":
            with self.transaction() as conn:
                conn.executescript(sql)
        else:
            raise DatabaseError(
                "executescript() is not supported for PostgreSQL. "
                "Use execute() for individual statements or use a migration tool."
            )

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            try:
                self._conn.close()
                log.info("Database connection closed (%s)", self._db_type)
            except Exception as exc:
                log.warning("Error closing database connection: %s", exc)

    def get_underlying_connection(self) -> Any:
        """Get underlying database connection (for advanced use)."""
        return self._conn


def get_database_from_env() -> Database:
    """
    Create Database instance from environment variables.

    Priority:
    1. TFP_DATABASE_URL (full connection string)
    2. TFP_DB_PATH (SQLite path only, backward compatible)
    3. Default SQLite path (./pib.db)

    Returns:
        Database instance configured for the environment

    Raises:
        DatabaseError: If database connection fails or is unreachable
    """
    # Check for PostgreSQL or explicit database URL
    database_url = os.environ.get("TFP_DATABASE_URL", "").strip()
    if database_url:
        db = Database.from_url(database_url)
        # Validate connection
        try:
            db.execute("SELECT 1")
            log.info("Database connection validated: %s", db.db_type)
        except Exception as exc:
            raise DatabaseError(f"Database connection failed: {exc}") from exc
        return db

    # Fallback to legacy TFP_DB_PATH (SQLite only)
    db_path = os.environ.get("TFP_DB_PATH", "pib.db").strip()
    if db_path == ":memory:":
        return Database.from_url("sqlite:///:memory:")
    return Database.from_url(f"sqlite:///{db_path}")
