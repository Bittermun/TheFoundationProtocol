import collections
import hashlib
import hmac as _hmac
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from tfp_broadcaster.broadcaster import Broadcaster
from tfp_client.lib.bridges.nostr_subscriber import NostrSubscriber
from tfp_client.lib.compute.credit_formula import CreditFormula
from tfp_client.lib.compute.task_executor import (
    TaskSpec,
    generate_content_verify_task,
    generate_hash_preimage_task,
    generate_matrix_verify_task,
)
from tfp_client.lib.compute.verify_habp import (
    HABPVerifier,
    generate_execution_proof,
)
from tfp_client.lib.core.tfp_engine import TFPClient
from tfp_client.lib.credit.ledger import MAX_SUPPLY, CreditLedger, Receipt
from tfp_client.lib.metadata.tag_index import TagOverlayIndex
from tfp_client.lib.ndn.adapter import Data, NDNAdapter

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "pib.db"

# Configure logging explicitly for security monitoring
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


@dataclass
class StoredContent:
    root_hash: str
    title: str
    tags: List[str]
    data: bytes


# ---------------------------------------------------------------------------
# Content store (SQLite-backed)
# ---------------------------------------------------------------------------


class ContentStore:
    """
    Persistent content store backed by SQLite with an in-memory tag index.

    The in-memory ``_tag_index`` maps tag → set[root_hash] for O(1) tag
    look-ups on the hot ``filter_by_tag`` path.  It is rebuilt from the DB
    on construction and kept in sync on every ``put``.
    """

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._tag_index: Dict[str, set] = {}  # tag → {root_hash, ...}
        self._init_schema()
        self._rebuild_tag_index()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content (
                root_hash TEXT PRIMARY KEY,
                title     TEXT NOT NULL,
                tags      TEXT NOT NULL,
                data      BLOB NOT NULL
            )
            """
        )
        self._conn.commit()

    def _rebuild_tag_index(self) -> None:
        """Rebuild the in-memory tag index from the current DB rows."""
        self._tag_index.clear()
        rows = self._conn.execute("SELECT root_hash, tags FROM content").fetchall()
        for root_hash, tags_json in rows:
            for tag in json.loads(tags_json):
                self._tag_index.setdefault(tag, set()).add(root_hash)

    def put(self, item: StoredContent) -> None:
        with self._db_lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO content (root_hash, title, tags, data) VALUES (?, ?, ?, ?)",
                (item.root_hash, item.title, json.dumps(item.tags), item.data),
            )
            self._conn.commit()
            for tag in item.tags:
                self._tag_index.setdefault(tag, set()).add(item.root_hash)

    def get(self, root_hash: str) -> Optional[StoredContent]:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT root_hash, title, tags, data FROM content WHERE root_hash = ?",
                (root_hash,),
            ).fetchone()
            if row is None:
                return None
            return StoredContent(
                root_hash=row[0],
                title=row[1],
                tags=json.loads(row[2]),
                data=row[3],
            )

    def all(self, limit: int = 100, offset: int = 0) -> List[StoredContent]:
        with self._db_lock:
            rows = self._conn.execute(
                "SELECT root_hash, title, tags, data FROM content ORDER BY rowid DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            return [
                StoredContent(
                    root_hash=r[0], title=r[1], tags=json.loads(r[2]), data=r[3]
                )
                for r in rows
            ]

    def filter_by_tag(
        self, tag: str, limit: int = 100, offset: int = 0
    ) -> List[StoredContent]:
        """Return items matching *tag* using the in-memory index (O(n_matches))."""
        with self._db_lock:
            hashes = self._tag_index.get(tag, set())
            if not hashes:
                return []
            # Use parameterized query with validated hash values to prevent SQL injection
            placeholders = ",".join("?" * len(hashes))
            rows = self._conn.execute(
                "SELECT root_hash, title, tags, data FROM content"
                f" WHERE root_hash IN ({placeholders})"
                " ORDER BY rowid DESC LIMIT ? OFFSET ?",
                [*list(hashes), limit, offset],
            ).fetchall()
            return [
                StoredContent(
                    root_hash=r[0], title=r[1], tags=json.loads(r[2]), data=r[3]
                )
                for r in rows
            ]

    def count_tag(self, tag: str) -> int:
        """Return the number of items matching tag."""
        with self._db_lock:
            return len(self._tag_index.get(tag, set()))

    def filter_by_tags(
        self, tags: List[str], limit: int = 100, offset: int = 0
    ) -> List[StoredContent]:
        """
        Return items that match ANY of the given tags (union semantics).

        Uses the in-memory tag index to collect root hashes, then does a
        single bulk IN-query — O(n_matches), not O(N_total).
        """
        with self._db_lock:
            hashes: set = set()
            for tag in tags:
                hashes |= self._tag_index.get(tag, set())
            if not hashes:
                return []
            # Use parameterized query with validated hash values to prevent SQL injection
            placeholders = ",".join("?" * len(hashes))
            rows = self._conn.execute(
                "SELECT root_hash, title, tags, data FROM content"
                f" WHERE root_hash IN ({placeholders})"
                " ORDER BY rowid DESC LIMIT ? OFFSET ?",
                [*list(hashes), limit, offset],
            ).fetchall()
            return [
                StoredContent(
                    root_hash=r[0], title=r[1], tags=json.loads(r[2]), data=r[3]
                )
                for r in rows
            ]

    def count_tags(self, tags: List[str]) -> int:
        """Return total items matching ANY of the given tags."""
        with self._db_lock:
            hashes: set = set()
            for tag in tags:
                hashes |= self._tag_index.get(tag, set())
            return len(hashes)

    def contains(self, root_hash: str) -> bool:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT 1 FROM content WHERE root_hash = ?", (root_hash,)
            ).fetchone()
            return row is not None

    def count(self) -> int:
        with self._db_lock:
            return self._conn.execute("SELECT COUNT(*) FROM content").fetchone()[0]


# ---------------------------------------------------------------------------
# Device registry (SQLite-backed)
# ---------------------------------------------------------------------------


class DeviceRegistry:
    """Stores enrolled device PUF entropy for request-signing verification."""

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._init_schema()

    def _init_schema(self) -> None:
        with self._db_lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    device_id   TEXT PRIMARY KEY,
                    puf_entropy BLOB NOT NULL,
                    enrolled_at REAL NOT NULL
                )
                """
            )
            self._conn.commit()

    def enroll(self, device_id: str, puf_entropy: bytes) -> None:
        with self._db_lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO devices (device_id, puf_entropy, enrolled_at) "
                "VALUES (?, ?, ?)",
                (device_id, puf_entropy, time.time()),
            )
            self._conn.commit()

    def get_entropy(self, device_id: str) -> Optional[bytes]:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT puf_entropy FROM devices WHERE device_id = ?", (device_id,)
            ).fetchone()
            return bytes(row[0]) if row else None

    def is_enrolled(self, device_id: str) -> bool:
        return self.get_entropy(device_id) is not None

    def count(self) -> int:
        """Return the total number of enrolled devices."""
        with self._db_lock:
            return self._conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]


def _verify_device_sig(
    device_id: str,
    sig_hex: str,
    message: str,
    registry: DeviceRegistry,
) -> bool:
    """Verify HMAC-SHA-256(puf_entropy, message) == sig_hex (constant-time)."""
    puf_entropy = registry.get_entropy(device_id)
    if puf_entropy is None:
        return False
    expected = _hmac.new(puf_entropy, message.encode(), hashlib.sha256).hexdigest()
    return _hmac.compare_digest(expected, sig_hex)


# ---------------------------------------------------------------------------
# Earn log — prevents credit replay (duplicate task_id per device)
# ---------------------------------------------------------------------------


class EarnLog:
    """
    SQLite-backed deduplication log for ``/api/earn`` calls.

    Each (device_id, task_id) pair is stored exactly once.  A second attempt
    to record the same pair returns ``False`` so the caller can reject it with
    HTTP 409 rather than silently minting extra credits.
    """

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._init_schema()

    def _init_schema(self) -> None:
        with self._db_lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS earn_log (
                    device_id TEXT NOT NULL,
                    task_id   TEXT NOT NULL,
                    earned_at REAL NOT NULL,
                    PRIMARY KEY (device_id, task_id)
                )
                """
            )
            self._conn.commit()

    def record(self, device_id: str, task_id: str) -> bool:
        """Attempt to record an earn event.  Returns True if new, False if duplicate."""
        with self._db_lock:
            try:
                self._conn.execute(
                    "INSERT INTO earn_log (device_id, task_id, earned_at) VALUES (?, ?, ?)",
                    (device_id, task_id, time.time()),
                )
                self._conn.commit()
                return True
            except sqlite3.IntegrityError:
                return False


# ---------------------------------------------------------------------------
# Credit store — persists ledger state across server restarts
# ---------------------------------------------------------------------------


class CreditStore:
    """
    SQLite-backed persistence for per-device CreditLedger state.

    Stores the hash chain, current balance, and the unspent receipt hashes so
    the ledger can be fully reconstructed after a server restart.
    """

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._init_schema()

    def _init_schema(self) -> None:
        with self._db_lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS credit_ledger (
                    device_id             TEXT PRIMARY KEY,
                    balance               INTEGER NOT NULL DEFAULT 0,
                    chain_json            TEXT    NOT NULL DEFAULT '[]',
                    unspent_receipts_json TEXT    NOT NULL DEFAULT '[]'
                )
                """
            )
            self._conn.commit()

    def save(self, device_id: str, client: "TFPClient") -> None:
        """Persist the client's current ledger + unspent receipts."""
        chain_json = json.dumps([h.hex() for h in client.ledger.chain])
        balance = client.ledger.balance
        unspent_json = json.dumps([r.chain_hash.hex() for r in client._earned_receipts])
        with self._db_lock:
            self._conn.execute(
                """
                INSERT INTO credit_ledger (device_id, balance, chain_json, unspent_receipts_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    balance               = excluded.balance,
                    chain_json            = excluded.chain_json,
                    unspent_receipts_json = excluded.unspent_receipts_json
                """,
                (device_id, balance, chain_json, unspent_json),
            )
            self._conn.commit()

    def load(self, device_id: str) -> Optional["TFPClient"]:
        """
        Restore a TFPClient with a persisted ledger, or return None if no
        record exists for this device.
        """
        with self._db_lock:
            row = self._conn.execute(
                "SELECT balance, chain_json, unspent_receipts_json FROM credit_ledger WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            if row is None:
                return None
            balance, chain_json, unspent_json = row
            chain = [bytes.fromhex(h) for h in json.loads(chain_json)]
            ledger = CreditLedger.from_snapshot(chain, balance)
            unspent_receipts = [
                Receipt(chain_hash=bytes.fromhex(h), credits=10)
                for h in json.loads(unspent_json)
            ]
            client = TFPClient(ndn=DemoNDNAdapter(_content_store), ledger=ledger)
            client._earned_receipts = unspent_receipts
            return client


# ---------------------------------------------------------------------------
# Task store — SQLite-backed compute task registry
# ---------------------------------------------------------------------------


class TaskStore:
    """
    Persistent store for compute tasks, bids, and results.

    Tasks flow through these states:
      open → bidding → assigned → verifying → completed | failed
    """

    _GENERATORS = {
        "hash_preimage": generate_hash_preimage_task,
        "matrix_verify": generate_matrix_verify_task,
        "content_verify": generate_content_verify_task,
    }

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.RLock) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._habp = HABPVerifier(consensus_threshold=3, redundancy_factor=5)
        self._credit_formula = CreditFormula()
        # RLock so that submit_result() (outer) can call increment_total_minted() (inner)
        # without deadlocking on re-entry.
        self._lock = threading.RLock()
        self._init_schema()

    def _init_schema(self) -> None:
        with self._db_lock:
            self._conn.executescript(
                """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id      TEXT PRIMARY KEY,
                task_type    TEXT NOT NULL,
                difficulty   INT  NOT NULL,
                spec_json    TEXT NOT NULL,
                status       TEXT NOT NULL DEFAULT 'open',
                created_at   REAL NOT NULL,
                deadline     REAL NOT NULL,
                credit_reward INT NOT NULL DEFAULT 10
            );
            CREATE TABLE IF NOT EXISTS task_results (
                result_id    INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id      TEXT NOT NULL,
                device_id    TEXT NOT NULL,
                output_hash  TEXT NOT NULL,
                exec_time_s  REAL NOT NULL,
                has_tee      INT  NOT NULL DEFAULT 0,
                submitted_at REAL NOT NULL,
                UNIQUE(task_id, device_id)
            );
            CREATE TABLE IF NOT EXISTS supply_ledger (
                id             INTEGER PRIMARY KEY CHECK (id = 1),
                total_minted   INTEGER NOT NULL DEFAULT 0
            );
            INSERT OR IGNORE INTO supply_ledger (id, total_minted) VALUES (1, 0);
            """
            )
        self._conn.commit()
        # Rebuild in-memory HABP state from persisted results for tasks still verifying
        self._rebuild_habp_from_db()

    def _rebuild_habp_from_db(self) -> None:
        """Replay persisted proofs into HABPVerifier so consensus survives restarts."""
        rows = self._conn.execute(
            """
            SELECT r.task_id, r.device_id, r.output_hash, r.exec_time_s, r.has_tee
            FROM task_results r
            JOIN tasks t ON t.task_id = r.task_id
            WHERE t.status IN ('verifying', 'open')
            ORDER BY r.submitted_at
            """
        ).fetchall()
        for task_id, device_id, output_hash, exec_time_s, has_tee in rows:
            proof = generate_execution_proof(
                device_id=device_id,
                task_id=task_id,
                output_data=bytes.fromhex(output_hash)
                if len(output_hash) == 64
                else output_hash.encode(),
                execution_time=exec_time_s,
                has_tee=bool(has_tee),
            )
            proof.output_hash = output_hash
            self._habp.submit_proof(proof)
        if rows:
            log.info(
                "Rebuilt HABP state from %d persisted proofs across %d tasks",
                len(rows),
                len(set(r[0] for r in rows)),
            )

    # -- Supply tracking -------------------------------------------------------

    def get_total_minted(self) -> int:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT total_minted FROM supply_ledger WHERE id = 1"
            ).fetchone()
            return row[0] if row else 0

    def increment_total_minted(self, amount: int) -> int:
        """Atomically increment and return new total. Raises if cap exceeded."""
        with self._db_lock:
            with self._lock:
                current = self.get_total_minted()
                if current + amount > MAX_SUPPLY:
                    from tfp_client.lib.credit.ledger import SupplyCapError

                    raise SupplyCapError(
                        f"Global supply cap reached: {current}/{MAX_SUPPLY}"
                    )
                new_total = current + amount
                self._conn.execute(
                    "UPDATE supply_ledger SET total_minted = ? WHERE id = 1",
                    (new_total,),
                )
                self._conn.commit()
                return new_total

    # -- Task lifecycle --------------------------------------------------------

    def create_task(self, task_type: str, difficulty: int, seed: bytes) -> TaskSpec:
        """Generate and persist a new compute task."""
        task_id = hashlib.sha3_256(
            seed + task_type.encode() + str(time.time()).encode()
        ).hexdigest()[:16]
        if task_type == "content_verify":
            spec = generate_content_verify_task(
                task_id=task_id, difficulty=difficulty, content=seed
            )
        else:
            gen = self._GENERATORS.get(task_type)
            if gen is None:
                raise ValueError(f"Unknown task_type: {task_type!r}")
            spec = gen(task_id=task_id, difficulty=difficulty, seed=seed)
        with self._db_lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO tasks
                  (task_id, task_type, difficulty, spec_json, status, created_at, deadline, credit_reward)
                VALUES (?, ?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    spec.task_id,
                    spec.task_type.value,
                    spec.difficulty,
                    json.dumps(spec.to_dict()),
                    spec.created_at,
                    spec.deadline,
                    spec.credit_reward,
                ),
            )
            self._conn.commit()
        return spec

    def list_open_tasks(self, limit: int = 20) -> List[dict]:
        """Return open tasks suitable for device consumption (reaps expired first)."""
        self.reap_expired_tasks()
        now = time.time()
        with self._db_lock:
            rows = self._conn.execute(
                """
                SELECT task_id, task_type, difficulty, credit_reward, deadline
                FROM tasks
                WHERE status = 'open' AND deadline > ?
                ORDER BY created_at
                LIMIT ?
                """,
                (now, limit),
            ).fetchall()
            return [
                {
                    "task_id": r[0],
                    "task_type": r[1],
                    "difficulty": r[2],
                    "credit_reward": r[3],
                    "deadline": r[4],
                    "time_left_s": round(r[4] - now),
                }
                for r in rows
            ]

    def reap_expired_tasks(self) -> int:
        """
        Mark all open/verifying tasks past their deadline as failed.

        Returns the count of tasks reaped. Called automatically before listing
        open tasks so the pool never shows stale entries.
        """
        now = time.time()
        with self._db_lock:
            with self._lock:
                cur = self._conn.execute(
                    """
                    UPDATE tasks SET status = 'failed'
                    WHERE status IN ('open', 'verifying') AND deadline < ?
                    """,
                    (now,),
                )
                self._conn.commit()
                reaped = cur.rowcount
        if reaped:
            log.info("Reaped %d expired tasks", reaped)
        return reaped

    def get_spec(self, task_id: str) -> Optional[TaskSpec]:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT spec_json FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
            if row is None:
                return None
            return TaskSpec.from_dict(json.loads(row[0]))

    def get_task_row(self, task_id: str) -> Optional[dict]:
        with self._db_lock:
            row = self._conn.execute(
                "SELECT task_id, task_type, difficulty, status, credit_reward, created_at, deadline "
                "FROM tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "task_id": row[0],
                "task_type": row[1],
                "difficulty": row[2],
                "status": row[3],
                "credit_reward": row[4],
                "created_at": row[5],
                "deadline": row[6],
            }

    def submit_result(
        self,
        task_id: str,
        device_id: str,
        output_hash: str,
        exec_time_s: float,
        has_tee: bool = False,
    ) -> dict:
        """
        Accept a result submission.

        Returns a dict with keys: status, verified, credits_earned (0 if not yet verified),
        and consensus_needed (how many more proofs are required for consensus).

        The entire method runs under both locks to serialize concurrent
        submissions and prevent HABP proof accumulation (self-mint attack).
        """
        with self._db_lock:
            with self._lock:
                task_row = self.get_task_row(task_id)
                if task_row is None:
                    raise HTTPException(status_code=404, detail="task not found")
                if task_row["status"] in ("completed", "failed"):
                    raise HTTPException(
                        status_code=409, detail="task already finalised"
                    )
                if time.time() > task_row["deadline"]:
                    self._conn.execute(
                        "UPDATE tasks SET status = 'failed' WHERE task_id = ?",
                        (task_id,),
                    )
                    self._conn.commit()
                    raise HTTPException(status_code=410, detail="task deadline passed")

                # Record result — UNIQUE(task_id, device_id) prevents duplicate rows.
                # Check rowcount: if 0 the device already submitted for this task and
                # we must NOT add another HABP proof (would allow a single device to
                # accumulate enough proofs to reach consensus alone — self-mint attack).
                cursor = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO task_results
                      (task_id, device_id, output_hash, exec_time_s, has_tee, submitted_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        device_id,
                        output_hash,
                        exec_time_s,
                        int(has_tee),
                        time.time(),
                    ),
                )
                if cursor.rowcount == 0:
                    raise HTTPException(
                        status_code=409,
                        detail="result already submitted for this device and task",
                    )
                self._conn.execute(
                    "UPDATE tasks SET status = 'verifying' WHERE task_id = ? AND status = 'open'",
                    (task_id,),
                )
                self._conn.commit()

                # Build HABP proof and attempt consensus
                proof = generate_execution_proof(
                    device_id=device_id,
                    task_id=task_id,
                    output_data=bytes.fromhex(output_hash)
                    if len(output_hash) == 64
                    else output_hash.encode(),
                    execution_time=exec_time_s,
                    has_tee=has_tee,
                )
                # Override the output_hash with what the device reported
                proof.output_hash = output_hash
                self._habp.submit_proof(proof)

                consensus = self._habp.verify_consensus(task_id)
                if consensus and consensus.verified:
                    # Mark completed and compute credits
                    calc = self._credit_formula.calculate_credits(
                        difficulty=task_row["difficulty"],
                        hardware_trust=consensus.credit_weight,
                        uptime_hours=24.0,
                        verification_confidence=consensus.confidence,
                        is_charging=False,
                    )
                    credits = calc.final_credits
                    self._conn.execute(
                        "UPDATE tasks SET status = 'completed' WHERE task_id = ?",
                        (task_id,),
                    )
                    self._conn.commit()
                    return {
                        "status": "verified",
                        "verified": True,
                        "credits_earned": credits,
                        "consensus_needed": 0,
                        "matching_devices": consensus.matching_devices,
                        "confidence": consensus.confidence,
                    }

                # Count current proofs
                proof_count = self._habp.get_proof_count(task_id)
                needed = max(0, 3 - proof_count)
                return {
                    "status": "pending_consensus",
                    "verified": False,
                    "credits_earned": 0,
                    "consensus_needed": needed,
                    "proofs_received": proof_count,
                }

    def stats(self) -> dict:
        """Return aggregate task statistics."""
        with self._db_lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) FROM tasks GROUP BY status"
            ).fetchall()
            counts = {r[0]: r[1] for r in rows}
            return {
                "open": counts.get("open", 0),
                "verifying": counts.get("verifying", 0),
                "completed": counts.get("completed", 0),
                "failed": counts.get("failed", 0),
                "total": sum(counts.values()),
                "total_minted": self.get_total_minted(),
                "supply_cap": MAX_SUPPLY,
                "supply_remaining": MAX_SUPPLY - self.get_total_minted(),
            }

    def device_leaderboard(self, limit: int = 50) -> List[dict]:
        """
        Return top contributing devices sorted by credits earned (balance).

        Joins the devices table with credit_ledger for balance and
        task_results for number of tasks contributed.
        """
        with self._db_lock:
            rows = self._conn.execute(
                """
                SELECT
                    d.device_id,
                    d.enrolled_at,
                    COALESCE(cl.balance, 0)          AS credits_balance,
                    COUNT(DISTINCT tr.task_id)        AS tasks_contributed,
                    MAX(tr.submitted_at)              AS last_active
                FROM devices d
                LEFT JOIN credit_ledger cl ON cl.device_id = d.device_id
                LEFT JOIN task_results   tr ON tr.device_id = d.device_id
                GROUP BY d.device_id
                ORDER BY credits_balance DESC, tasks_contributed DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "device_id": r[0],
                    "enrolled_at": r[1],
                    "credits_balance": r[2],
                    "tasks_contributed": r[3],
                    "last_active": r[4],
                }
                for r in rows
            ]

    def device_stats(self, device_id: str) -> Optional[dict]:
        """
        Return stats for a single device — O(1) direct query.
        Returns None if the device has never contributed a task.
        """
        with self._db_lock:
            row = self._conn.execute(
                """
                SELECT
                    d.device_id,
                    d.enrolled_at,
                    COALESCE(cl.balance, 0)          AS credits_balance,
                    COUNT(DISTINCT tr.task_id)        AS tasks_contributed,
                    MAX(tr.submitted_at)              AS last_active
                FROM devices d
                LEFT JOIN credit_ledger cl ON cl.device_id = d.device_id
                LEFT JOIN task_results   tr ON tr.device_id = d.device_id
                WHERE d.device_id = ?
                GROUP BY d.device_id
                """,
                (device_id,),
            ).fetchone()
            if row is None:
                return None
            return {
                "device_id": row[0],
                "enrolled_at": row[1],
                "credits_balance": row[2],
                "tasks_contributed": row[3],
                "last_active": row[4],
            }


# ---------------------------------------------------------------------------
# Prometheus metrics (in-process counters)
# ---------------------------------------------------------------------------


class _Metrics:
    """
    Lightweight in-process counters for Prometheus text exposition format.
    No external dependency — pure Python.  For production, swap to
    prometheus_client if desired.

    Counters are seeded from SQLite on startup so they survive server restarts.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = {
            "tfp_tasks_created_total": 0,
            "tfp_tasks_completed_total": 0,
            "tfp_tasks_failed_total": 0,
            "tfp_results_submitted_total": 0,
            "tfp_credits_minted_total": 0,
            "tfp_credits_spent_total": 0,
            "tfp_content_published_total": 0,
            "tfp_content_served_total": 0,
            "tfp_devices_enrolled_total": 0,
            "tfp_earn_rate_limited_total": 0,
            "tfp_earn_replay_rejected_total": 0,
            "tfp_auth_failures_total": 0,
        }

    def seed_from_db(self, conn: sqlite3.Connection) -> None:
        """
        Seed durable counters from SQLite so they survive server restarts.

        Only counters that can be derived from persisted data are seeded;
        transient counters (rate_limited, replay_rejected, auth_failures)
        intentionally reset to 0 on restart.
        """
        try:
            tasks_row = conn.execute(
                "SELECT SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),"
                "       SUM(CASE WHEN status='failed'    THEN 1 ELSE 0 END),"
                "       COUNT(*) FROM tasks"
            ).fetchone()
            devices_row = conn.execute("SELECT COUNT(*) FROM devices").fetchone()
            supply_row = conn.execute(
                "SELECT total_minted FROM supply_ledger WHERE id = 1"
            ).fetchone()
            content_row = conn.execute("SELECT COUNT(*) FROM content").fetchone()
            results_row = conn.execute("SELECT COUNT(*) FROM task_results").fetchone()
            with self._lock:
                self._counters["tfp_tasks_completed_total"] = tasks_row[0] or 0
                self._counters["tfp_tasks_failed_total"] = tasks_row[1] or 0
                self._counters["tfp_tasks_created_total"] = tasks_row[2] or 0
                self._counters["tfp_devices_enrolled_total"] = devices_row[0] or 0
                self._counters["tfp_credits_minted_total"] = (
                    supply_row[0] if supply_row else 0
                )
                self._counters["tfp_content_published_total"] = content_row[0] or 0
                self._counters["tfp_results_submitted_total"] = results_row[0] or 0
        except Exception as exc:
            log.warning("metrics.seed_from_db failed (non-fatal): %s", exc)

    def inc(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def get(self, name: str) -> int:
        return self._counters.get(name, 0)

    def snapshot(self) -> Dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def to_prometheus_text(self) -> str:
        lines = []
        with self._lock:
            for name, value in sorted(self._counters.items()):
                lines.append(f"# TYPE {name} counter")
                lines.append(f"{name} {value}")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Rate limiter — sliding-window token bucket per device
# ---------------------------------------------------------------------------

_EARN_RATE_MAX = int(os.environ.get("TFP_EARN_RATE_MAX", "10"))
_EARN_RATE_WINDOW = int(os.environ.get("TFP_EARN_RATE_WINDOW", "60"))

# Per-device rate limit for task result submissions: default 30 per minute.
# Prevents a single device from spamming the HABP verifier.
_RESULT_RATE_MAX = int(os.environ.get("TFP_RESULT_RATE_MAX", "30"))
_RESULT_RATE_WINDOW = int(os.environ.get("TFP_RESULT_RATE_WINDOW", "60"))


class _RateLimiter:
    """
    In-memory sliding-window rate limiter.

    Allows at most ``max_calls`` calls per ``window_seconds`` per key.
    Thread-safe by virtue of the GIL on CPython; each bucket is a deque of
    float timestamps that is pruned on every check.
    """

    def __init__(
        self, max_calls: int = _EARN_RATE_MAX, window_seconds: int = _EARN_RATE_WINDOW
    ) -> None:
        self._max = max_calls
        self._window = window_seconds
        self._buckets: Dict[str, collections.deque] = {}

    def is_allowed(self, key: str) -> bool:
        """Return True and record the call, or False if the rate limit is exceeded."""
        now = time.monotonic()
        bucket = self._buckets.setdefault(key, collections.deque())
        cutoff = now - self._window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self._max:
            return False
        bucket.append(now)
        return True

    def reset(self, key: str) -> None:
        """Clear the bucket for a key (useful in tests)."""
        self._buckets.pop(key, None)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PublishRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    text: str = Field(min_length=1, max_length=20000)
    tags: List[str] = Field(default_factory=list)
    device_id: str = Field(min_length=1, max_length=120)


class EarnRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    task_id: str = Field(min_length=1, max_length=256)


class EnrollRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    puf_entropy_hex: str = Field(min_length=64, max_length=64)


class CreateTaskRequest(BaseModel):
    task_type: str = Field(default="hash_preimage")
    difficulty: int = Field(default=3, ge=1, le=10)
    seed_hex: str = Field(default="", max_length=128)


class SubmitResultRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=120)
    output_hash: str = Field(min_length=64, max_length=64)  # SHA3-256 hex
    exec_time_s: float = Field(ge=0.0)
    has_tee: bool = Field(default=False)


# ---------------------------------------------------------------------------
# App state (initialised in lifespan)
# ---------------------------------------------------------------------------

_content_store: Optional[ContentStore] = None
_device_registry: Optional[DeviceRegistry] = None
_earn_log: Optional[EarnLog] = None
_credit_store: Optional[CreditStore] = None
_task_store: Optional[TaskStore] = None
_earn_rate_limiter: _RateLimiter = _RateLimiter()
_result_rate_limiter: _RateLimiter = _RateLimiter()
_tag_overlay: Optional[TagOverlayIndex] = None
_nostr_subscriber: Optional[NostrSubscriber] = None
_broadcaster = Broadcaster()
_clients: Dict[str, TFPClient] = {}
_metrics: _Metrics = _Metrics()
_demo_dir = Path(__file__).resolve().parent.parent / "demo"


class DemoNDNAdapter(NDNAdapter):
    def __init__(self, store: ContentStore):
        self._store = store

    def express_interest(self, interest):
        root_hash = interest.name.rsplit("/", 1)[-1]
        item = self._store.get(root_hash)
        if item is None:
            raise ValueError("content not found")
        return Data(name=interest.name, content=item.data)


def _make_ndn_adapter() -> NDNAdapter:
    """Return the real NDN adapter when TFP_REAL_ADAPTERS=1, else the demo store adapter."""
    if os.environ.get("TFP_REAL_ADAPTERS", "").strip() == "1":
        from tfp_client.lib.ndn.ndn_real import RealNDNAdapter

        return RealNDNAdapter()
    return DemoNDNAdapter(_content_store)


def _client_for(device_id: str) -> TFPClient:
    """Return (and cache) a TFPClient for *device_id*, restoring persisted state if available."""
    if device_id not in _clients:
        restored = _credit_store.load(device_id) if _credit_store else None
        if restored is not None:
            # Patch the NDN adapter to point at the current store instance
            restored.ndn = _make_ndn_adapter()
            _clients[device_id] = restored
        else:
            kwargs: dict = {"ndn": _make_ndn_adapter()}
            if os.environ.get("TFP_REAL_ADAPTERS", "").strip() == "1":
                from tfp_client.lib.fountain.fountain_real import RealRaptorQAdapter
                from tfp_client.lib.zkp.zkp_real import RealZKPAdapter

                kwargs["raptorq"] = RealRaptorQAdapter()
                kwargs["zkp"] = RealZKPAdapter()
            _clients[device_id] = TFPClient(**kwargs)
    return _clients[device_id]


def _normalize_tags(tags: List[str]) -> List[str]:
    cleaned: List[str] = []
    for tag in tags:
        value = tag.strip().lower()
        if value:
            cleaned.append(value)
    return sorted(set(cleaned))


def _seed_sample() -> None:
    sample = (
        "Welcome to Scholo Radio demo. "
        "This sample content is seeded on startup so anyone can test retrieval in under 60 seconds."
    ).encode()
    result = _broadcaster.seed_content(
        sample, metadata={"title": "Welcome Sample"}, use_ldm=False
    )
    _content_store.put(
        StoredContent(
            root_hash=result["root_hash"],
            title="Welcome Sample",
            tags=["demo", "welcome", "audio"],
            data=sample,
        )
    )


def _preseed_tasks() -> None:
    """Pre-create a small pool of open tasks so devices can join immediately."""
    if _task_store is None:
        return
    _task_store.reap_expired_tasks()
    if _task_store.stats()["open"] >= 5:
        return  # Already have enough open tasks
    seeds = [
        ("hash_preimage", 2, b"tfp-seed-hp-1"),
        ("hash_preimage", 3, b"tfp-seed-hp-2"),
        ("matrix_verify", 2, b"tfp-seed-mv-1"),
        ("matrix_verify", 3, b"tfp-seed-mv-2"),
        ("content_verify", 2, b"tfp-seed-cv-1"),
    ]
    for task_type, difficulty, seed in seeds:
        try:
            _task_store.create_task(task_type, difficulty, seed)
        except Exception as exc:
            log.warning("preseed task %s failed: %s", task_type, exc)


def _on_nostr_event(event_dict: dict) -> None:
    """Callback: ingest a remote TFP Nostr announcement into the tag overlay."""
    try:
        payload = json.loads(event_dict.get("content", "{}"))
        content_hash_hex = payload.get("hash", "")
        tags = payload.get("tags", [])
        if content_hash_hex and len(content_hash_hex) == 64:
            content_hash_bytes = bytes.fromhex(content_hash_hex)
            domain = payload.get("domain", "general")
            _tag_overlay.add_entry(
                domain=domain,
                tags=tags if tags else ["nostr"],
                content_hash=content_hash_bytes,
                popularity=0.5,
            )
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError) as e:
        log.warning("Failed to process Nostr event: %s", e)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global \
        _content_store, \
        _device_registry, \
        _earn_log, \
        _credit_store, \
        _task_store, \
        _earn_rate_limiter, \
        _result_rate_limiter, \
        _tag_overlay, \
        _nostr_subscriber, \
        _clients, \
        _metrics
    db_path = os.environ.get("TFP_DB_PATH", str(_DEFAULT_DB_PATH))
    _conn = sqlite3.connect(db_path, check_same_thread=False)
    # WAL mode: allows concurrent reads while a write is in progress.
    # Dramatically reduces "database is locked" errors under load.
    if db_path != ":memory:":
        _conn.execute("PRAGMA journal_mode=WAL")
    # Single shared lock for all stores to serialize access to the shared connection
    _db_lock = threading.RLock()
    _content_store = ContentStore(_conn, _db_lock)
    _device_registry = DeviceRegistry(_conn, _db_lock)
    _earn_log = EarnLog(_conn, _db_lock)
    _credit_store = CreditStore(_conn, _db_lock)
    _task_store = TaskStore(_conn, _db_lock)
    _earn_rate_limiter = _RateLimiter(
        max_calls=_EARN_RATE_MAX, window_seconds=_EARN_RATE_WINDOW
    )
    _result_rate_limiter = _RateLimiter(
        max_calls=_RESULT_RATE_MAX, window_seconds=_RESULT_RATE_WINDOW
    )
    _metrics = _Metrics()
    # Seed durable counters from SQLite so they survive restarts
    _metrics.seed_from_db(_conn)
    _tag_overlay = TagOverlayIndex()
    _clients.clear()
    if _content_store.count() == 0:
        _seed_sample()
    # Pre-populate a few open tasks so devices can immediately join
    _preseed_tasks()

    # Background maintenance thread — reaps expired tasks and replenishes pool
    # every 30 s without requiring any HTTP traffic to trigger it.
    _stop_maintenance = threading.Event()

    def _maintenance_loop() -> None:
        while not _stop_maintenance.wait(timeout=30):
            try:
                if _task_store is not None:
                    _task_store.reap_expired_tasks()
                    _preseed_tasks()
            except Exception as exc:
                log.warning("maintenance loop error (non-fatal): %s", exc)

    _maint_thread = threading.Thread(
        target=_maintenance_loop, name="tfp-maintenance", daemon=True
    )
    _maint_thread.start()

    # Start Nostr subscriber in offline mode unless NOSTR_RELAY is set
    relay_url = os.environ.get("NOSTR_RELAY", "")
    _nostr_subscriber = NostrSubscriber(
        relay_url=relay_url or "wss://relay.damus.io",
        on_event=_on_nostr_event,
        offline=not relay_url,
    )
    _nostr_subscriber.start()

    yield

    _stop_maintenance.set()
    _nostr_subscriber.stop()
    _conn.close()
    _content_store = None
    _device_registry = None
    _earn_log = None
    _credit_store = None
    _task_store = None
    _tag_overlay = None
    _nostr_subscriber = None


app = FastAPI(title="TFP Demo Node", version="0.2.0", lifespan=lifespan)

# Add CORS middleware for cross-origin security
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "content_items": _content_store.count()}


@app.get("/")
def demo_page():
    return FileResponse(_demo_dir / "index.html")


@app.get("/manifest.json")
def manifest():
    return FileResponse(
        _demo_dir / "manifest.json", media_type="application/manifest+json"
    )


@app.get("/service-worker.js")
def service_worker():
    return FileResponse(
        _demo_dir / "service-worker.js", media_type="application/javascript"
    )


@app.get("/api/content")
def search_content(
    tag: str | None = Query(default=None, min_length=1),
    tags: str | None = Query(
        default=None, description="Comma-separated tags (union match)"
    ),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """
    Search or list published content.

    - ``tag`` — filter by a single tag (exact, case-insensitive)
    - ``tags`` — comma-separated list of tags, returns items matching **any** tag (union)
    - ``limit`` / ``offset`` — pagination; response includes ``total``

    If both ``tag`` and ``tags`` are supplied, ``tags`` takes precedence.
    """
    if tags:
        tag_list = [t.strip().lower() for t in tags.split(",") if t.strip()]
        items = _content_store.filter_by_tags(tag_list, limit=limit, offset=offset)
        total = _content_store.count_tags(tag_list)
    elif tag:
        t = tag.strip().lower()
        items = _content_store.filter_by_tag(t, limit=limit, offset=offset)
        total = _content_store.count_tag(t)
    else:
        items = _content_store.all(limit=limit, offset=offset)
        total = _content_store.count()
    return {
        "items": [
            {"root_hash": item.root_hash, "title": item.title, "tags": item.tags}
            for item in items
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.post("/api/enroll")
def enroll(payload: EnrollRequest) -> dict:
    try:
        puf_entropy = bytes.fromhex(payload.puf_entropy_hex)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="puf_entropy_hex must be valid hex"
        ) from exc
    _device_registry.enroll(payload.device_id, puf_entropy)
    _metrics.inc("tfp_devices_enrolled_total")
    return {"enrolled": True, "device_id": payload.device_id}


@app.post("/api/publish")
def publish(
    payload: PublishRequest,
    x_device_sig: str = Header(alias="X-Device-Sig"),
) -> dict:
    message = f"{payload.device_id}:{payload.title}"
    if not _verify_device_sig(
        payload.device_id, x_device_sig, message, _device_registry
    ):
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=401,
            detail="invalid or missing device signature — enroll first via /api/enroll",
        )
    body = payload.text.encode()
    result = _broadcaster.seed_content(
        body, metadata={"title": payload.title}, use_ldm=False
    )
    tags = _normalize_tags(payload.tags)
    _content_store.put(
        StoredContent(
            root_hash=result["root_hash"],
            title=payload.title,
            tags=tags,
            data=body,
        )
    )
    _metrics.inc("tfp_content_published_total")
    return {
        "root_hash": result["root_hash"],
        "title": payload.title,
        "tags": tags,
        "status": "broadcasting",
    }


@app.post("/api/earn")
def earn(
    payload: EarnRequest,
    x_device_sig: str = Header(alias="X-Device-Sig"),
) -> dict:
    message = f"{payload.device_id}:{payload.task_id}"
    if not _verify_device_sig(
        payload.device_id, x_device_sig, message, _device_registry
    ):
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=401,
            detail="invalid or missing device signature — enroll first via /api/enroll",
        )
    # Rate-limit check (sliding window per device)
    if not _earn_rate_limiter.is_allowed(payload.device_id):
        _metrics.inc("tfp_earn_rate_limited_total")
        raise HTTPException(
            status_code=429,
            detail=f"rate limit exceeded — max {_EARN_RATE_MAX} earn calls per {_EARN_RATE_WINDOW}s per device",
        )
    # Deduplication — reject replayed task IDs
    if not _earn_log.record(payload.device_id, payload.task_id):
        _metrics.inc("tfp_earn_replay_rejected_total")
        raise HTTPException(
            status_code=409,
            detail="task_id already processed — each task may only be submitted once",
        )
    client = _client_for(payload.device_id)
    # Inject network-wide total so supply cap is enforced
    client.ledger.set_network_total_minted(
        _task_store.get_total_minted() if _task_store else 0
    )
    receipt = client.submit_compute_task(payload.task_id)
    if _task_store:
        _task_store.increment_total_minted(receipt.credits)
    # Persist updated ledger so credits survive a server restart
    _credit_store.save(payload.device_id, client)
    _metrics.inc("tfp_credits_minted_total", receipt.credits)
    return {
        "device_id": payload.device_id,
        "task_id": payload.task_id,
        "credits_earned": receipt.credits,
        "chain_hash": receipt.chain_hash.hex(),
    }


@app.get("/api/get/{root_hash}")
def get_content(root_hash: str, device_id: str = Query(default="web-demo")) -> dict:
    item = _content_store.get(root_hash)
    if item is None:
        raise HTTPException(status_code=404, detail="content not found")

    client = _client_for(device_id)
    try:
        content = client.request_content(root_hash)
    except ValueError as exc:
        if "no earned credits" in str(exc):
            raise HTTPException(
                status_code=402, detail="earn credits first via /api/earn"
            ) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    _metrics.inc("tfp_content_served_total")
    _metrics.inc("tfp_credits_spent_total")
    return {
        "root_hash": content.root_hash,
        "title": item.title,
        "tags": item.tags,
        "text": content.data.decode(errors="replace"),
        "sha3": hashlib.sha3_256(content.data).hexdigest(),
    }


@app.get("/api/status")
def status() -> dict:
    """Node status: local content count, tag index stats, and Nostr subscriber state."""
    nostr_events = len(_nostr_subscriber.get_received()) if _nostr_subscriber else 0
    task_stats = _task_store.stats() if _task_store else {}
    return {
        "version": "0.3.0",
        "content_items": _content_store.count(),
        "nostr_events_received": nostr_events,
        "nostr_subscriber_running": _nostr_subscriber.is_running()
        if _nostr_subscriber
        else False,
        "nostr_relay": _nostr_subscriber.relay_url if _nostr_subscriber else None,
        "tasks": task_stats,
        "supply_cap": MAX_SUPPLY,
        "metrics": _metrics.snapshot(),
    }


@app.get("/api/discovery")
def discovery(domain: str = Query(default="general")) -> dict:
    """
    Return content hashes discovered via Nostr announcements for a domain.

    These are remote peer announcements propagated through the Nostr relay;
    they supplement the local ``/api/content`` index.
    """
    try:
        epoch = TagOverlayIndex._get_current_epoch()
        dag = _tag_overlay.build_merkle_dag(epoch=epoch, domain=domain)
        entries = [
            {
                "content_hash": entry.content_hash.hex(),
                "tag": entry.tag,
                "popularity": entry.popularity_score,
            }
            for entry in dag.entries
        ]
    except (AttributeError, TypeError, ValueError) as e:
        log.warning("Failed to build Merkle DAG for domain %s: %s", domain, e)
        entries = []
    return {"domain": domain, "entries": entries, "source": "nostr"}


# ---------------------------------------------------------------------------
# Compute task dispatch API
# ---------------------------------------------------------------------------


@app.post("/api/task")
def create_task(
    payload: CreateTaskRequest,
    x_device_sig: str = Header(alias="X-Device-Sig", default=""),
) -> dict:
    """
    Create a new compute task and broadcast it to the mesh.

    Any enrolled device may call this; unenrolled devices may create tasks
    without auth (tasks are public goods).
    """
    seed_bytes = bytes.fromhex(payload.seed_hex) if payload.seed_hex else os.urandom(16)
    try:
        spec = _task_store.create_task(
            task_type=payload.task_type,
            difficulty=payload.difficulty,
            seed=seed_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _metrics.inc("tfp_tasks_created_total")
    return {
        "task_id": spec.task_id,
        "task_type": spec.task_type.value,
        "difficulty": spec.difficulty,
        "credit_reward": spec.credit_reward,
        "deadline": spec.deadline,
        # Include enough input data for device to execute the task
        "input_data_hex": spec.input_data.hex(),
        "expected_output_hash": spec.expected_output_hash,
    }


@app.get("/api/tasks")
def list_tasks(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """
    Return open tasks available for device execution.

    ``open_count`` is the total number of open tasks in the pool (may be larger
    than ``limit``).  Use it to determine whether more tasks are available.
    """
    tasks = _task_store.list_open_tasks(limit=limit)
    stats = _task_store.stats()
    return {"tasks": tasks, "open_count": stats.get("open", 0)}


@app.get("/api/task/{task_id}")
def get_task(task_id: str) -> dict:
    """Get details and current status of a specific task."""
    row = _task_store.get_task_row(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    spec = _task_store.get_spec(task_id)
    result = {**row}
    if spec is not None:
        result["input_data_hex"] = spec.input_data.hex()
        result["expected_output_hash"] = spec.expected_output_hash
    return result


@app.post("/api/task/{task_id}/result")
def submit_task_result(
    task_id: str,
    payload: SubmitResultRequest,
    x_device_sig: str = Header(alias="X-Device-Sig"),
) -> dict:
    """
    Submit a compute result for a task.

    The device must be enrolled and provide a valid signature.
    Credits are minted only after HABP consensus (3/5 matching results).

    When credits_earned > 0 the caller should follow up with POST /api/earn
    (using the task_id as proof) to credit their ledger, or the credits are
    automatically applied if the device is already tracked server-side.
    """
    message = f"{payload.device_id}:{task_id}"
    if not _verify_device_sig(
        payload.device_id, x_device_sig, message, _device_registry
    ):
        _metrics.inc("tfp_auth_failures_total")
        raise HTTPException(
            status_code=401,
            detail="invalid or missing device signature — enroll first via /api/enroll",
        )

    if not _result_rate_limiter.is_allowed(payload.device_id):
        raise HTTPException(
            status_code=429,
            detail=(
                f"result submission rate limit exceeded — max {_RESULT_RATE_MAX}"
                f" per {_RESULT_RATE_WINDOW}s per device"
            ),
        )

    verification = _task_store.submit_result(
        task_id=task_id,
        device_id=payload.device_id,
        output_hash=payload.output_hash,
        exec_time_s=payload.exec_time_s,
        has_tee=payload.has_tee,
    )
    _metrics.inc("tfp_results_submitted_total")

    if verification["verified"]:
        _metrics.inc("tfp_tasks_completed_total")
        credits = verification["credits_earned"]
        # Auto-apply credits to the device's ledger if consensus is reached
        if credits > 0 and not _earn_log.record(
            payload.device_id, f"task:{task_id}:result"
        ):
            # Already applied (idempotent guard)
            pass
        elif credits > 0:
            client = _client_for(payload.device_id)
            client.ledger.set_network_total_minted(_task_store.get_total_minted())
            try:
                proof_material = f"{task_id}:{payload.output_hash}".encode()
                proof_hash = hashlib.sha3_256(proof_material).digest()
                receipt = client.ledger.mint(credits, proof_hash)
                client._earned_receipts.append(receipt)
                _task_store.increment_total_minted(credits)
                _credit_store.save(payload.device_id, client)
                _metrics.inc("tfp_credits_minted_total", credits)
            except Exception as exc:
                log.warning(
                    "Auto-mint failed for device=%s task=%s credits=%d: %s",
                    payload.device_id,
                    task_id,
                    credits,
                    exc,
                )

        # Replenish task pool
        try:
            _preseed_tasks()
        except Exception as exc:
            log.warning("Task pool replenish failed: %s", exc)

    return verification


# ---------------------------------------------------------------------------
# Device leaderboard
# ---------------------------------------------------------------------------


@app.get("/api/devices")
def device_leaderboard_endpoint(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """
    Return all enrolled devices sorted by credits earned (descending).

    Useful for leaderboards, network health checks, and federation tooling.
    ``total_enrolled`` reflects the true count of all devices, regardless of
    the ``limit`` parameter.
    """
    devices = _task_store.device_leaderboard(limit=limit)
    return {
        "devices": devices,
        "total_enrolled": _device_registry.count(),
    }


@app.get("/api/device/{device_id}")
def get_device(device_id: str) -> dict:
    """Return stats for a single enrolled device."""
    if not _device_registry.is_enrolled(device_id):
        raise HTTPException(status_code=404, detail="device not enrolled")
    match = _task_store.device_stats(device_id)
    if match is None:
        # Enrolled but no task contributions yet
        match = {
            "device_id": device_id,
            "enrolled_at": None,
            "credits_balance": 0,
            "tasks_contributed": 0,
            "last_active": None,
        }
    client = _clients.get(device_id)
    match["credits_in_memory"] = client.ledger.balance if client else None
    return match


# ---------------------------------------------------------------------------
# Prometheus metrics endpoint
# ---------------------------------------------------------------------------


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus-compatible text metrics endpoint."""
    return Response(
        content=_metrics.to_prometheus_text(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

_ADMIN_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>TFP Admin — Scholo Node</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:system-ui,sans-serif;background:#0f0f14;color:#e0e0e8;padding:24px}
    h1{font-size:1.5rem;font-weight:700;color:#7c6fcd;margin-bottom:4px}
    .sub{color:#888;font-size:.85rem;margin-bottom:24px}
    .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px;margin-bottom:32px}
    .card{background:#1a1a24;border:1px solid #2a2a38;border-radius:12px;padding:20px}
    .card .label{font-size:.75rem;color:#888;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px}
    .card .value{font-size:2rem;font-weight:700;color:#a89cef}
    .card .sub-value{font-size:.8rem;color:#666;margin-top:4px}
    table{width:100%;border-collapse:collapse;background:#1a1a24;border-radius:8px;overflow:hidden;margin-bottom:32px}
    th{text-align:left;padding:10px 16px;background:#222230;font-size:.8rem;color:#888;text-transform:uppercase}
    td{padding:10px 16px;font-size:.9rem;border-top:1px solid #2a2a38}
    tr:hover td{background:#20202e}
    .badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:.75rem;font-weight:600}
    .open{background:#1e3a2a;color:#4caf78}
    .completed{background:#1a2e4a;color:#5b9cf6}
    .verifying{background:#3a2a0e;color:#f0a030}
    .failed{background:#3a1a1a;color:#f06060}
    .refresh{margin-top:24px;color:#666;font-size:.8rem}
    .progress{background:#1a1a24;border-radius:99px;height:8px;margin-top:8px;overflow:hidden}
    .progress-bar{height:100%;background:linear-gradient(90deg,#7c6fcd,#a89cef);border-radius:99px;transition:width .4s}
    h2{margin-bottom:12px;font-size:1.1rem;color:#888}
  </style>
</head>
<body>
  <h1>⚡ TFP Node Admin</h1>
  <div class="sub" id="version">Loading…</div>

  <div class="grid" id="cards"></div>

  <h2>Open Tasks</h2>
  <table><thead><tr>
    <th>Task ID</th><th>Type</th><th>Difficulty</th><th>Reward</th><th>Time Left</th>
  </tr></thead><tbody id="tasks-body"></tbody></table>

  <h2>Device Leaderboard</h2>
  <table><thead><tr>
    <th>#</th><th>Device ID</th><th>Credits</th><th>Tasks</th><th>Last Active</th>
  </tr></thead><tbody id="devices-body"></tbody></table>

  <div class="refresh">Auto-refreshes every 5 seconds ·
    <a href="/api/status" style="color:#7c6fcd">Raw JSON</a> ·
    <a href="/api/devices" style="color:#7c6fcd">Devices</a> ·
    <a href="/metrics" style="color:#7c6fcd">Prometheus</a>
  </div>

  <script>
    async function refresh() {
      const [s, t, dv] = await Promise.all([
        fetch('/api/status').then(r=>r.json()).catch(()=>({})),
        fetch('/api/tasks').then(r=>r.json()).catch(()=>({tasks:[]})),
        fetch('/api/devices').then(r=>r.json()).catch(()=>({devices:[]})),
      ]);
      const tasks_s = s.tasks || {};
      const metrics_s = s.metrics || {};
      const supply_used = tasks_s.total_minted || 0;
      const supply_cap = s.supply_cap || 21000000;
      const pct = Math.min(100, (supply_used / supply_cap * 100)).toFixed(4);

      document.getElementById('version').textContent =
        `v${s.version || '?'} · Content: ${s.content_items||0} · Supply: ${supply_used.toLocaleString()} / ${supply_cap.toLocaleString()} credits`;

      const cards = [
        {label:'Open Tasks', value: tasks_s.open||0, sub:'awaiting devices'},
        {label:'Completed', value: tasks_s.completed||0, sub:'verified by consensus'},
        {label:'Credits Minted', value: (metrics_s.tfp_credits_minted_total||0).toLocaleString(), sub:`of ${supply_cap.toLocaleString()} cap`},
        {label:'Credits Spent', value: (metrics_s.tfp_credits_spent_total||0).toLocaleString(), sub:'on content access'},
        {label:'Devices Enrolled', value: metrics_s.tfp_devices_enrolled_total||0, sub:'unique devices'},
        {label:'Content Served', value: metrics_s.tfp_content_served_total||0, sub:'requests fulfilled'},
        {label:'Nostr Events', value: s.nostr_events_received||0, sub: s.nostr_subscriber_running?'live':'offline'},
        {label:'Supply Used', value: pct+'%', sub:'<div class="progress"><div class="progress-bar" style="width:'+pct+'%"></div></div>'},
      ];
      document.getElementById('cards').innerHTML = cards.map(c=>
        `<div class="card"><div class="label">${c.label}</div><div class="value">${c.value}</div><div class="sub-value">${c.sub}</div></div>`
      ).join('');

      const rows = (t.tasks||[]).map(tk=>`<tr>
        <td><code>${tk.task_id}</code></td>
        <td>${tk.task_type}</td>
        <td>${tk.difficulty}</td>
        <td>${tk.credit_reward} cr</td>
        <td>${tk.time_left_s}s</td>
      </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:#555">No open tasks</td></tr>';
      document.getElementById('tasks-body').innerHTML = rows;

      const drows = (dv.devices||[]).slice(0,20).map((d,i)=>`<tr>
        <td>${i+1}</td>
        <td><code>${d.device_id}</code></td>
        <td>${(d.credits_balance||0).toLocaleString()}</td>
        <td>${d.tasks_contributed||0}</td>
        <td>${d.last_active ? new Date(d.last_active*1000).toLocaleTimeString() : '—'}</td>
      </tr>`).join('') || '<tr><td colspan="5" style="text-align:center;color:#555">No devices yet</td></tr>';
      document.getElementById('devices-body').innerHTML = drows;
    }
    refresh();
    setInterval(refresh, 5000);
  </script>
</body>
</html>
"""


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard() -> HTMLResponse:
    """Live admin dashboard — shows node health, task pool, and credit supply."""
    return HTMLResponse(content=_ADMIN_HTML)
