# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 The Foundation Protocol Contributors

"""
Unified TFPNode API for TFP v4.0

The canonical interface for publishing, fetching, and deduplicating information
across decentralized mesh topologies.
"""

import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .cdc import ChunkRecipe, ContentDefinedChunker
from .fountain import FountainCodec, FountainDroplet
from .merkle import MerkleTree

log = logging.getLogger(__name__)


class TFPNode:
    """A self-contained Foundation Protocol node instance with optional SQLite persistence."""

    def __init__(
        self,
        node_id: str = "tfp_local_01",
        target_chunk_size: int = 1024,
        symbol_size: int = 256,
        db_path: Path | str | None = None,
        chunker: ContentDefinedChunker | None = None,
        codec: FountainCodec | None = None,
    ):
        self._bulletins: dict[tuple[str, int], dict[str, Any]] = {}
        self._bulletin_watermarks: dict[tuple[str, str], dict[str, Any]] = {}
        self._bulletin_lock = threading.RLock()
        self.node_id = node_id
        resolved_db = db_path if db_path is not None else os.environ.get("TFP_DB_PATH")
        # Per-operation SQLite connections cannot share ':memory:'. Use this
        # node's existing isolated memory store for the explicit ephemeral mode.
        self.db_path: Path | None = Path(resolved_db) if resolved_db and str(resolved_db) != ":memory:" else None

        if chunker is not None:
            self.chunker = chunker
        else:
            self.chunker = ContentDefinedChunker(
                min_size=max(256, target_chunk_size // 2),
                max_size=target_chunk_size * 4,
                target_size=target_chunk_size,
            )

        if codec is not None:
            self.codec = codec
        else:
            self.codec = FountainCodec(symbol_size=symbol_size)
        self.chunk_store: dict[str, bytes] = {}
        self.recipes: dict[str, ChunkRecipe] = {}
        self.droplet_store: dict[str, list[FountainDroplet]] = {}
        self.merkle_trees: dict[str, MerkleTree] = {}
        self.telemetry = {
            "total_bytes_published": 0,
            "total_droplet_bytes_published": 0,
            "total_chunks_stored": 0,
            "unique_chunks_stored": 0,
            "bandwidth_saved_pct": 0.0,
            "successful_reconstructions": 0,
        }

        if self.db_path:
            self._init_db()

    def _init_db(self) -> None:
        """Initialize SQLite schema for persistent node storage."""
        if not self.db_path:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS recipes (
                    root_hash TEXT PRIMARY KEY,
                    total_size INTEGER,
                    chunk_hashes_json TEXT,
                    chunk_sizes_json TEXT,
                    metadata_json TEXT,
                    created_at REAL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_hash TEXT PRIMARY KEY,
                    data BLOB
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS droplets (
                    root_hash TEXT,
                    seed INTEGER,
                    degree INTEGER,
                    data BLOB,
                    PRIMARY KEY (root_hash, seed)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bulletins (
                    bulletin_id TEXT,
                    revision INTEGER,
                    content_hash TEXT,
                    root_hash TEXT,
                    publisher_id TEXT,
                    signature_hex TEXT,
                    title TEXT,
                    received_at REAL,
                    verified_status TEXT,
                    data_size INTEGER,
                    metadata_json TEXT,
                    PRIMARY KEY (bulletin_id, revision)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bulletin_watermarks (
                    publisher_id TEXT NOT NULL,
                    bulletin_id TEXT NOT NULL,
                    max_revision INTEGER NOT NULL,
                    latest_content_hash TEXT NOT NULL,
                    latest_root_hash TEXT NOT NULL,
                    latest_title TEXT,
                    first_seen_at REAL DEFAULT 0.0,
                    last_seen_at REAL DEFAULT 0.0,
                    updated_at REAL DEFAULT 0.0,
                    PRIMARY KEY (publisher_id, bulletin_id)
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bulletin_watermarks_bid ON bulletin_watermarks(bulletin_id)
                """
            )
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(bulletin_watermarks)")
            cols = {row[1] for row in cur.fetchall()}
            if "latest_title" not in cols:
                conn.execute("ALTER TABLE bulletin_watermarks ADD COLUMN latest_title TEXT")
                cols.add("latest_title")
            if "updated_at" not in cols:
                conn.execute("ALTER TABLE bulletin_watermarks ADD COLUMN updated_at REAL DEFAULT 0.0")
                cols.add("updated_at")
            if "first_seen_at" not in cols:
                conn.execute("ALTER TABLE bulletin_watermarks ADD COLUMN first_seen_at REAL DEFAULT 0.0")
                cols.add("first_seen_at")
            if "last_seen_at" not in cols:
                conn.execute("ALTER TABLE bulletin_watermarks ADD COLUMN last_seen_at REAL DEFAULT 0.0")
                cols.add("last_seen_at")

            # Check if bulletins table exists before backfill
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='bulletins'")
            if cur.fetchone():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO bulletin_watermarks (
                        publisher_id, bulletin_id, max_revision, latest_content_hash, latest_root_hash, latest_title, first_seen_at, last_seen_at, updated_at
                    )
                    SELECT b.publisher_id, b.bulletin_id, b.revision, b.content_hash, b.root_hash, b.title, b.received_at, b.received_at, b.received_at
                    FROM bulletins b
                    INNER JOIN (
                        SELECT publisher_id, bulletin_id, MAX(revision) AS max_rev
                        FROM bulletins
                        GROUP BY publisher_id, bulletin_id
                    ) m ON b.publisher_id = m.publisher_id AND b.bulletin_id = m.bulletin_id AND b.revision = m.max_rev;
                    """
                )
                conn.execute(
                    """
                    UPDATE bulletin_watermarks
                    SET latest_content_hash = (
                        SELECT b.content_hash FROM bulletins b
                        WHERE b.publisher_id = bulletin_watermarks.publisher_id
                          AND b.bulletin_id = bulletin_watermarks.bulletin_id
                        ORDER BY b.revision DESC LIMIT 1
                    ),
                    latest_root_hash = (
                        SELECT b.root_hash FROM bulletins b
                        WHERE b.publisher_id = bulletin_watermarks.publisher_id
                          AND b.bulletin_id = bulletin_watermarks.bulletin_id
                        ORDER BY b.revision DESC LIMIT 1
                    ),
                    latest_title = (
                        SELECT b.title FROM bulletins b
                        WHERE b.publisher_id = bulletin_watermarks.publisher_id
                          AND b.bulletin_id = bulletin_watermarks.bulletin_id
                        ORDER BY b.revision DESC LIMIT 1
                    )
                    WHERE EXISTS (
                        SELECT 1 FROM bulletins b
                        WHERE b.publisher_id = bulletin_watermarks.publisher_id
                          AND b.bulletin_id = bulletin_watermarks.bulletin_id
                    );
                    """
                )
                conn.execute(
                    """
                    UPDATE bulletin_watermarks
                    SET first_seen_at = (
                        SELECT MIN(b.received_at) FROM bulletins b
                        WHERE b.publisher_id = bulletin_watermarks.publisher_id
                          AND b.bulletin_id = bulletin_watermarks.bulletin_id
                    ),
                    last_seen_at = (
                        SELECT MAX(b.received_at) FROM bulletins b
                        WHERE b.publisher_id = bulletin_watermarks.publisher_id
                          AND b.bulletin_id = bulletin_watermarks.bulletin_id
                    )
                    WHERE EXISTS (
                        SELECT 1 FROM bulletins b
                        WHERE b.publisher_id = bulletin_watermarks.publisher_id
                          AND b.bulletin_id = bulletin_watermarks.bulletin_id
                    );
                    """
                )
                conn.execute(
                    """
                    UPDATE bulletin_watermarks
                    SET first_seen_at = CASE WHEN first_seen_at IS NULL OR first_seen_at = 0.0 THEN updated_at ELSE first_seen_at END,
                        last_seen_at = CASE WHEN last_seen_at IS NULL OR last_seen_at = 0.0 THEN updated_at ELSE last_seen_at END,
                        updated_at = CASE WHEN updated_at IS NULL OR updated_at = 0.0 THEN last_seen_at ELSE updated_at END
                    """
                )

            # Synchronize in-memory cache with durable database watermarks
            cur.execute(
                "SELECT publisher_id, bulletin_id, max_revision, latest_content_hash, latest_root_hash, latest_title, first_seen_at, last_seen_at, updated_at FROM bulletin_watermarks"
            )
            for pub, bid, max_rev, c_hash, r_hash, l_title, first_at, last_at, up_at in cur.fetchall():
                self._bulletin_watermarks[(pub, bid)] = {
                    "publisher_id": pub,
                    "bulletin_id": bid,
                    "max_revision": max_rev,
                    "latest_content_hash": c_hash,
                    "latest_root_hash": r_hash,
                    "latest_title": l_title,
                    "first_seen_at": first_at,
                    "last_seen_at": last_at,
                    "updated_at": up_at,
                }
            conn.commit()
        finally:
            conn.close()

    def _persist_content(
        self,
        recipe: ChunkRecipe,
        chunks: list[bytes],
        droplets: list[FountainDroplet],
        connection: sqlite3.Connection | None = None,
    ) -> None:
        """Persist recipe, chunks, and droplets to SQLite database."""
        if not self.db_path:
            return
        conn = connection if connection is not None else sqlite3.connect(str(self.db_path))
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO recipes
                (root_hash, total_size, chunk_hashes_json, chunk_sizes_json, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    recipe.root_hash,
                    recipe.total_size,
                    json.dumps(recipe.chunk_hashes),
                    json.dumps(recipe.chunk_sizes),
                    json.dumps(recipe.metadata),
                    time.time(),
                ),
            )
            chunk_rows = [(h, b) for h, b in zip(recipe.chunk_hashes, chunks)]
            conn.executemany(
                "INSERT OR REPLACE INTO chunks (chunk_hash, data) VALUES (?, ?)",
                chunk_rows,
            )
            droplet_rows = [
                (recipe.root_hash, d.seed, d.degree, d.serialize())
                for d in droplets
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO droplets (root_hash, seed, degree, data) VALUES (?, ?, ?, ?)",
                droplet_rows,
            )
            if connection is None:
                conn.commit()
        finally:
            if connection is None:
                conn.close()

    def _load_recipe_from_db(self, root_hash: str) -> bool:
        """Attempt to restore recipe, chunks, and droplets for root_hash from SQLite."""
        if not self.db_path or not self.db_path.exists():
            return False
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT root_hash, total_size, chunk_hashes_json, chunk_sizes_json, metadata_json FROM recipes WHERE root_hash = ?",
                (root_hash,),
            )
            row = cursor.fetchone()
            if not row:
                return False

            r_hash, total_size, hashes_json, sizes_json, meta_json = row
            try:
                recipe = ChunkRecipe(
                    root_hash=r_hash,
                    total_size=total_size,
                    chunk_hashes=json.loads(hashes_json),
                    chunk_sizes=json.loads(sizes_json),
                    metadata=json.loads(meta_json) if meta_json else {},
                )
            except Exception as exc:
                log.warning(f"Malformed recipe JSON in DB for root {root_hash}: {exc}")
                return False

            if not recipe.validate(expected_root=root_hash):
                log.warning(f"Recipe validation failed for root {root_hash}: chunk sequence does not match root")
                return False

            self.recipes[r_hash] = recipe

            # Load chunks
            cursor.execute(
                f"SELECT chunk_hash, data FROM chunks WHERE chunk_hash IN ({','.join(['?'] * len(recipe.chunk_hashes))})",
                recipe.chunk_hashes,
            )
            for chash, cdata in cursor.fetchall():
                self.chunk_store[chash] = cdata

            # Load droplets
            cursor.execute(
                "SELECT data FROM droplets WHERE root_hash = ?",
                (root_hash,),
            )
            loaded_droplets = []
            sym_size = recipe.metadata.get("symbol_size", self.codec.symbol_size)
            for (d_blob,) in cursor.fetchall():
                try:
                    droplet = FountainDroplet.deserialize(d_blob, symbol_size=sym_size)
                    loaded_droplets.append(droplet)
                except Exception as exc:
                    log.warning(f"Malformed droplet blob skipped for root {root_hash}: {exc}")

            if loaded_droplets:
                self.droplet_store[root_hash] = loaded_droplets
                # Rebuild Merkle tree
                droplet_bytes = [d.serialize() for d in loaded_droplets]
                self.merkle_trees[root_hash] = MerkleTree(droplet_bytes)

            return True
        finally:
            conn.close()

    def publish(
        self,
        data: bytes,
        metadata: dict[str, Any] | None = None,
        redundancy: float | None = None,
    ) -> ChunkRecipe:
        """
        Publish binary data into the node:
        1. FastCDC 64-bit content chunking & deduplication
        2. Rateless fountain droplet encoding
        3. SHA3-256 Merkle tree authentication
        """
        if not data:
            raise ValueError("Payload cannot be empty")

        meta = dict(metadata or {})
        meta["symbol_size"] = self.codec.symbol_size
        recipe, chunks = self.chunker.create_recipe(data, metadata=meta)
        root_hash = recipe.root_hash

        # Store chunks in content-addressed chunk store
        for chunk_hash, chunk_bytes in zip(recipe.chunk_hashes, chunks):
            self.chunk_store[chunk_hash] = chunk_bytes

        self.recipes[root_hash] = recipe

        # Separate automatic redundancy policy from explicit settings
        k_blocks = (len(data) + self.codec.symbol_size - 1) // self.codec.symbol_size
        if redundancy is not None:
            effective_redundancy = max(0.0, float(redundancy))
        else:
            # Automatic policy calibrated for rateless loss resilience:
            # Small payloads (<=32 blocks) survive >=50% loss (Shannon limit requires >=1.0)
            # Medium payloads (<=128 blocks) survive >=25-33% loss
            # Large payloads (>128 blocks) maintain 100% redundancy baseline
            if k_blocks <= 8:
                effective_redundancy = 5.0
            elif k_blocks <= 32:
                effective_redundancy = 3.0
            elif k_blocks <= 128:
                effective_redundancy = 2.0
            else:
                effective_redundancy = 1.0

        droplets, _k, _orig_len = self.codec.encode(data, redundancy=effective_redundancy)
        self.droplet_store[root_hash] = droplets

        # Build Merkle tree over droplet serialized payloads
        droplet_bytes = [d.serialize() for d in droplets]
        mtree = MerkleTree(droplet_bytes)
        self.merkle_trees[root_hash] = mtree

        # Update telemetry
        self.telemetry["total_bytes_published"] += len(data)
        self.telemetry["total_droplet_bytes_published"] += sum(len(b) for b in droplet_bytes)
        self.telemetry["total_chunks_stored"] += len(chunks)
        self.telemetry["unique_chunks_stored"] = len(self.chunk_store)
        if self.telemetry["total_chunks_stored"] > 0:
            reused = self.telemetry["total_chunks_stored"] - self.telemetry["unique_chunks_stored"]
            self.telemetry["bandwidth_saved_pct"] = round(
                (reused / self.telemetry["total_chunks_stored"]) * 100.0, 1
            )

        self._persist_content(recipe, chunks, droplets)
        return recipe

    def fetch(
        self,
        root_hash: str,
        simulated_loss: float = 0.0,
        received_droplets: list[FountainDroplet] | None = None,
    ) -> bytes:
        """
        Fetch and reconstruct content from local or peer fountain droplet store,
        honestly recovering ONLY from received or surviving droplets.
        """
        if root_hash not in self.recipes:
            if not self._load_recipe_from_db(root_hash):
                raise KeyError(f"Content root hash {root_hash} not found on this node")

        recipe = self.recipes[root_hash]
        if not recipe.validate(expected_root=root_hash):
            raise ValueError(f"Stored recipe chunk sequence does not match root hash {root_hash}")

        # 1. Fast path: Direct assembly from locally stored verified chunks
        all_chunks_present = all(chash in self.chunk_store for chash in recipe.chunk_hashes)
        if all_chunks_present and simulated_loss == 0.0 and received_droplets is None:
            assembled = bytearray()
            verified = True
            for chash, csize in zip(recipe.chunk_hashes, recipe.chunk_sizes):
                cdata = self.chunk_store[chash]
                if len(cdata) != csize or not hmac.compare_digest(hashlib.sha3_256(cdata).hexdigest(), chash):
                    verified = False
                    break
                assembled.extend(cdata)

            if verified and len(assembled) == recipe.total_size:
                hasher = hashlib.sha3_256()
                for chash in recipe.chunk_hashes:
                    hasher.update(chash.encode("utf-8"))
                computed_root = hasher.hexdigest()
                if not hmac.compare_digest(computed_root, root_hash):
                    raise ValueError(f"Content root hash mismatch during fast-path assembly: {computed_root} != {root_hash}")

                self.telemetry["successful_reconstructions"] += 1
                return bytes(assembled)

        # 2. Fountain reconstruction path (for lossy network or missing chunks)
        droplets = self.droplet_store.get(root_hash, [])
        sym_size = recipe.metadata.get("symbol_size", self.codec.symbol_size)
        k = (recipe.total_size + sym_size - 1) // sym_size
        codec = self.codec if self.codec.symbol_size == sym_size else FountainCodec(symbol_size=sym_size)

        if received_droplets is not None:
            surviving = list(received_droplets)
        else:
            if not droplets:
                raise RuntimeError(f"No fountain droplets available for root {root_hash}")
            surviving = [d for d in droplets if (secrets.randbelow(1_000_000) / 1_000_000.0) >= simulated_loss]

        if not surviving:
            raise RuntimeError(f"Fountain decode failed for root {root_hash}: 0 surviving droplets under loss {simulated_loss}")

        try:
            reconstructed = codec.decode(
                surviving,
                k=k,
                orig_len=recipe.total_size,
            )
        except (ValueError, RuntimeError) as exc:
            raise RuntimeError(
                f"Fountain decode failed for root {root_hash} with {len(surviving)}/{len(droplets)} surviving droplets (k={k}): {exc}"
            ) from exc

        # Verify hash integrity against recipe chunk slices (independent of reader's FastCDC settings)
        offset = 0
        hasher = hashlib.sha3_256()
        for expected_hash, csize in zip(recipe.chunk_hashes, recipe.chunk_sizes):
            chunk_slice = reconstructed[offset : offset + csize]
            offset += csize
            slice_hash = hashlib.sha3_256(chunk_slice).hexdigest()
            if not hmac.compare_digest(slice_hash, expected_hash):
                raise ValueError(f"Chunk hash mismatch during verification: {slice_hash} != {expected_hash}")
            hasher.update(slice_hash.encode("utf-8"))
        recovered_root = hasher.hexdigest()

        if not hmac.compare_digest(recovered_root, root_hash):
            raise ValueError(f"Hash mismatch after reconstruction: {recovered_root} != {root_hash}")

        self.telemetry["successful_reconstructions"] += 1
        return reconstructed

    def inspect_recipe(self, root_hash: str) -> dict[str, Any]:
        """Inspect deterministic recipe and chunk hierarchy."""
        if root_hash not in self.recipes:
            if not self._load_recipe_from_db(root_hash):
                raise KeyError(f"Root hash {root_hash} not found")
        recipe = self.recipes[root_hash]
        mtree = self.merkle_trees.get(root_hash)
        return {
            "root_hash": recipe.root_hash,
            "total_size_bytes": recipe.total_size,
            "chunk_count": len(recipe.chunk_hashes),
            "chunk_hashes": recipe.chunk_hashes,
            "chunk_sizes": recipe.chunk_sizes,
            "merkle_root": mtree.root_hex if mtree else None,
            "metadata": recipe.metadata,
        }

    def list_recipes(self) -> list[ChunkRecipe]:
        """Return all recipes stored in memory and in the persistent SQLite database."""
        recipes = dict(self.recipes)
        if self.db_path and self.db_path.exists():
            conn = sqlite3.connect(str(self.db_path))
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT root_hash, total_size, chunk_hashes_json, chunk_sizes_json, metadata_json FROM recipes"
                )
                for r_hash, total_size, hashes_json, sizes_json, meta_json in cursor.fetchall():
                    if r_hash not in recipes:
                        try:
                            rec = ChunkRecipe(
                                root_hash=r_hash,
                                total_size=total_size,
                                chunk_hashes=json.loads(hashes_json),
                                chunk_sizes=json.loads(sizes_json),
                                metadata=json.loads(meta_json) if meta_json else {},
                            )
                            if rec.validate(expected_root=r_hash):
                                recipes[r_hash] = rec
                            else:
                                log.warning(f"Corrupted recipe skipped in DB for root {r_hash}")
                        except Exception as exc:
                            log.warning(f"Malformed recipe JSON skipped in DB for root {r_hash}: {exc}")
            finally:
                conn.close()
        return list(recipes.values())

    def get_telemetry(self) -> dict[str, Any]:
        """Return real deduplication and throughput metrics."""
        return dict(self.telemetry)

    def _check_watermark(
        self,
        bulletin_id: str,
        revision: int,
        content_hash: str,
        publisher_id: str,
        record: dict[str, Any],
        data: bytes,
        status: str,
        conn: sqlite3.Connection | None = None,
    ) -> ChunkRecipe | None:
        """Verify watermark constraints and return existing recipe on authentic duplicate replay."""
        from .bulletin_identity import (
            PublisherIdentityConflictError,
            RevisionConflictError,
            StaleRevisionError,
        )

        if conn is not None:
            wm_rows = conn.execute(
                "SELECT max_revision, latest_content_hash, latest_root_hash, publisher_id, latest_title FROM bulletin_watermarks WHERE bulletin_id=?",
                (bulletin_id,),
            ).fetchall()
        else:
            wm_rows = [
                (wm["max_revision"], wm["latest_content_hash"], wm["latest_root_hash"], wm["publisher_id"], wm.get("latest_title"))
                for (pub, bid), wm in self._bulletin_watermarks.items()
                if bid == bulletin_id
            ]

        if not wm_rows:
            return None

        for wm_rev, wm_c_hash, wm_r_hash, wm_pub, wm_title in wm_rows:
            if wm_pub != publisher_id:
                raise PublisherIdentityConflictError("Bulletin publisher identity conflict")
            if revision < wm_rev:
                raise StaleRevisionError(
                    f"Stale bulletin revision was not accepted: revision {revision} is superseded by known watermark {wm_rev}"
                )
            if revision == wm_rev:
                stored = self.get_bulletin(bulletin_id, revision, connection=conn)
                expected_title = stored[0]["title"] if stored is not None else wm_title
                incoming_title = record.get("title", bulletin_id)

                matches_content = hmac.compare_digest(content_hash, wm_c_hash)
                canonical_expected_title = expected_title if (expected_title is not None and expected_title != "") else bulletin_id
                matches_title = (incoming_title == canonical_expected_title)

                if not matches_content or not matches_title:
                    raise RevisionConflictError(
                        f"Bulletin revision conflict: Bulletin {bulletin_id} rev {revision} conflict: differing title or content"
                    )

                if wm_r_hash not in self.recipes:
                    if conn is not None:
                        self._load_recipe_from_db(wm_r_hash)

                if wm_r_hash in self.recipes:
                    root_hash_to_use = wm_r_hash
                    recipe = self.recipes[wm_r_hash]
                else:
                    staged = TFPNode(db_path="", chunker=self.chunker, codec=self.codec)
                    recipe = staged.publish(data, metadata=record)
                    root_hash_to_use = recipe.root_hash
                    self.chunk_store.update(staged.chunk_store)
                    self.recipes.update(staged.recipes)
                    self.droplet_store.update(staged.droplet_store)
                    self.merkle_trees.update(staged.merkle_trees)
                    if conn is not None:
                        self._persist_content(
                            recipe,
                            [staged.chunk_store[h] for h in recipe.chunk_hashes],
                            staged.droplet_store[root_hash_to_use],
                            connection=conn,
                        )

                if stored is not None:
                    accepted = stored[0]
                else:
                    # Reconstruct metadata or re-admit display record for pruned authentic bulletin
                    accepted = dict(record)
                    accepted["root_hash"] = root_hash_to_use
                    accepted["title"] = incoming_title
                    if conn is not None:
                        conn.execute(
                            """INSERT OR REPLACE INTO bulletins
                            (bulletin_id, revision, content_hash, root_hash, publisher_id, signature_hex,
                             title, received_at, verified_status, data_size, metadata_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                bulletin_id,
                                revision,
                                content_hash,
                                root_hash_to_use,
                                publisher_id,
                                record.get("signature_hex"),
                                incoming_title,
                                record["received_at"],
                                status,
                                len(data),
                                json.dumps(accepted),
                            ),
                        )
                        conn.execute(
                            """UPDATE bulletin_watermarks
                            SET latest_title = ?, latest_root_hash = ?
                            WHERE publisher_id = ? AND bulletin_id = ?""",
                            (incoming_title, root_hash_to_use, publisher_id, bulletin_id),
                        )
                        conn.commit()
                    self._bulletins[(bulletin_id, revision)] = accepted
                    if (publisher_id, bulletin_id) in self._bulletin_watermarks:
                        self._bulletin_watermarks[(publisher_id, bulletin_id)]["latest_root_hash"] = root_hash_to_use
                        if not self._bulletin_watermarks[(publisher_id, bulletin_id)].get("latest_title"):
                            self._bulletin_watermarks[(publisher_id, bulletin_id)]["latest_title"] = incoming_title

                return replace(recipe, metadata=accepted)

        return None

    def store_bulletin(
        self, bulletin_id: str, revision: int, data: bytes, title: str = "",
        publisher_id: str = "unsigned", signature_hex: str | None = None,
        verified_status: str | None = None, metadata: dict[str, Any] | None = None,
        signature_version: int = 2,
    ) -> ChunkRecipe:
        """Verify, admit and persist a bulletin. Caller-supplied status is never evidence.

        SQLite admission and publication share one transaction. A local bulletin
        ID stays bound to its first publisher; this is not a publisher trust policy.
        """
        from .bulletin_identity import check_revision, verification_status

        if not data:
            raise ValueError("Bulletin payload data cannot be empty")
        title = title or bulletin_id
        content_hash = hashlib.sha3_256(data).hexdigest()
        status = verification_status(bulletin_id, revision, content_hash, publisher_id,
                                     signature_hex, title, signature_version)
        record = dict(metadata or {})
        record.update({
            "bulletin_id": bulletin_id, "revision": revision, "title": title,
            "publisher_id": publisher_id, "signature_hex": signature_hex,
            "verified_status": status, "signature_version": signature_version,
            "publisher_trust": "not_established", "content_hash": content_hash,
            "received_at": time.time(), "data_size": len(data),
        })
        with self._bulletin_lock:
            conn = sqlite3.connect(str(self.db_path)) if self.db_path else None
            try:
                if conn is not None:
                    conn.execute("BEGIN IMMEDIATE")

                duplicate_recipe = self._check_watermark(
                    bulletin_id=bulletin_id,
                    revision=revision,
                    content_hash=content_hash,
                    publisher_id=publisher_id,
                    record=record,
                    data=data,
                    status=status,
                    conn=conn,
                )
                if duplicate_recipe is not None:
                    return duplicate_recipe

                if conn is not None:
                    rows = conn.execute(
                        "SELECT revision, publisher_id, content_hash, title, root_hash FROM bulletins WHERE bulletin_id=?",
                        (bulletin_id,),
                    ).fetchall()
                    existing = [dict(zip(("revision", "publisher_id", "content_hash", "title", "root_hash"), row)) for row in rows]
                else:
                    existing = [r for (bid, _), r in self._bulletins.items() if bid == bulletin_id]

                duplicate = check_revision(existing, record)
                if duplicate is not None:
                    root = duplicate["root_hash"]
                    if root not in self.recipes:
                        if conn is not None:
                            self._load_recipe_from_db(root)
                    # Content-addressed recipes can be shared by distinct
                    # bulletins. Return this bulletin's provenance, not whichever
                    # metadata last happened to be stored for those same bytes.
                    stored = self.get_bulletin(bulletin_id, revision, connection=conn)
                    accepted = stored[0] if stored is not None else duplicate
                    if root in self.recipes:
                        return replace(self.recipes[root], metadata=accepted)
                    staged = TFPNode(db_path="", chunker=self.chunker, codec=self.codec)
                    recipe = staged.publish(data, metadata=accepted)
                    self.chunk_store.update(staged.chunk_store)
                    self.recipes.update(staged.recipes)
                    self.droplet_store.update(staged.droplet_store)
                    self.merkle_trees.update(staged.merkle_trees)
                    return recipe

                # Prepare without exposing rejected/uncommitted content in this node.
                staged = TFPNode(db_path="", chunker=self.chunker, codec=self.codec)
                recipe = staged.publish(data, metadata=record)
                root = recipe.root_hash
                record["root_hash"] = root
                if conn is not None:
                    self._persist_content(recipe, [staged.chunk_store[h] for h in recipe.chunk_hashes],
                                          staged.droplet_store[root], connection=conn)
                    conn.execute(
                        """INSERT INTO bulletins
                        (bulletin_id, revision, content_hash, root_hash, publisher_id, signature_hex,
                         title, received_at, verified_status, data_size, metadata_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (bulletin_id, revision, content_hash, root, publisher_id, signature_hex,
                         title, record["received_at"], status, len(data), json.dumps(record)),
                    )
                    conn.execute(
                        """INSERT INTO bulletin_watermarks
                        (publisher_id, bulletin_id, max_revision, latest_content_hash, latest_root_hash, first_seen_at, last_seen_at, latest_title, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(publisher_id, bulletin_id) DO UPDATE SET
                            max_revision = CASE WHEN excluded.max_revision > bulletin_watermarks.max_revision THEN excluded.max_revision ELSE bulletin_watermarks.max_revision END,
                            latest_content_hash = CASE WHEN excluded.max_revision >= bulletin_watermarks.max_revision THEN excluded.latest_content_hash ELSE bulletin_watermarks.latest_content_hash END,
                            latest_root_hash = CASE WHEN excluded.max_revision >= bulletin_watermarks.max_revision THEN excluded.latest_root_hash ELSE bulletin_watermarks.latest_root_hash END,
                            latest_title = CASE WHEN excluded.max_revision >= bulletin_watermarks.max_revision THEN excluded.latest_title ELSE bulletin_watermarks.latest_title END,
                            last_seen_at = excluded.last_seen_at,
                            updated_at = excluded.updated_at""",
                        (publisher_id, bulletin_id, revision, content_hash, root, record["received_at"], record["received_at"], title, record["received_at"]),
                    )
                    conn.commit()
                prev_wm = self._bulletin_watermarks.get((publisher_id, bulletin_id))
                first_seen = prev_wm.get("first_seen_at", record["received_at"]) if prev_wm else record["received_at"]
                self._bulletin_watermarks[(publisher_id, bulletin_id)] = {
                    "publisher_id": publisher_id,
                    "bulletin_id": bulletin_id,
                    "max_revision": max(revision, prev_wm.get("max_revision", 0) if prev_wm else 0),
                    "latest_content_hash": content_hash if (prev_wm is None or revision >= prev_wm.get("max_revision", 0)) else prev_wm.get("latest_content_hash"),
                    "latest_root_hash": root if (prev_wm is None or revision >= prev_wm.get("max_revision", 0)) else prev_wm.get("latest_root_hash"),
                    "latest_title": title if (prev_wm is None or revision >= prev_wm.get("max_revision", 0)) else prev_wm.get("latest_title"),
                    "first_seen_at": first_seen,
                    "last_seen_at": record["received_at"],
                    "updated_at": record["received_at"],
                }
                self.chunk_store.update(staged.chunk_store)
                self.recipes.update(staged.recipes)
                self.droplet_store.update(staged.droplet_store)
                self.merkle_trees.update(staged.merkle_trees)
                for key in ("total_bytes_published", "total_droplet_bytes_published", "total_chunks_stored"):
                    self.telemetry[key] += staged.telemetry[key]
                self.telemetry["unique_chunks_stored"] = len(self.chunk_store)
                total = self.telemetry["total_chunks_stored"]
                self.telemetry["bandwidth_saved_pct"] = round(100 * (total - len(self.chunk_store)) / total, 1)
                self._bulletins[(bulletin_id, revision)] = record
                return recipe
            finally:
                if conn is not None:
                    conn.close()

    def get_bulletin(
        self,
        bulletin_id: str,
        revision: int | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[dict[str, Any], bytes] | None:
        """
        Retrieve a bulletin's record and exact content bytes from authoritative storage.
        """
        if not self.db_path and connection is None:
            records = [r for (bid, rev), r in self._bulletins.items()
                       if bid == bulletin_id and (revision is None or revision == rev)]
            if not records:
                return None
            record = max(records, key=lambda r: r["revision"])
            return dict(record), self.fetch(record["root_hash"])
        if connection is None and (not self.db_path or not self.db_path.exists()):
            return None

        conn = connection or sqlite3.connect(str(self.db_path))
        close_conn = connection is None
        try:
            cur = conn.cursor()
            if revision is not None:
                cur.execute(
                    """
                    SELECT bulletin_id, revision, content_hash, root_hash, publisher_id, signature_hex, title, received_at, verified_status, data_size, metadata_json
                    FROM bulletins WHERE bulletin_id = ? AND revision = ?
                    """,
                    (bulletin_id, revision),
                )
            else:
                cur.execute(
                    """
                    SELECT bulletin_id, revision, content_hash, root_hash, publisher_id, signature_hex, title, received_at, verified_status, data_size, metadata_json
                    FROM bulletins WHERE bulletin_id = ? ORDER BY revision DESC LIMIT 1
                    """,
                    (bulletin_id,),
                )
            row = cur.fetchone()
            if not row:
                return None

            b_id, rev, c_hash, r_hash, pub_id, sig, title, recv_at, status, d_size, meta_json = row
            meta = json.loads(meta_json) if meta_json else {}
            meta.update({
                "bulletin_id": b_id,
                "revision": rev,
                "content_hash": c_hash,
                "root_hash": r_hash,
                "publisher_id": pub_id,
                "signature_hex": sig,
                "title": title,
                "received_at": recv_at,
                "verified_status": status,
                "data_size": d_size,
            })
            if status == "verified_ed25519" and meta.get("signature_version") != 2:
                meta["verified_status"] = "legacy_signature_unverified"
            meta["publisher_trust"] = "not_established"
            content_bytes = self.fetch(r_hash or c_hash)
            return meta, content_bytes
        finally:
            if close_conn:
                conn.close()

    def list_bulletins(self) -> list[dict[str, Any]]:
        """
        List all bulletins stored in authoritative storage.
        """
        if not self.db_path:
            return [dict(record) for record in self._bulletins.values()]
        if not self.db_path.exists():
            return []

        conn = sqlite3.connect(str(self.db_path))
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT bulletin_id, revision, content_hash, root_hash, publisher_id, signature_hex, title, received_at, verified_status, data_size, metadata_json
                FROM bulletins ORDER BY received_at DESC, bulletin_id ASC, revision DESC
                """
            )
            results = []
            for row in cur.fetchall():
                b_id, rev, c_hash, r_hash, pub_id, sig, title, recv_at, status, d_size, meta_json = row
                meta = json.loads(meta_json) if meta_json else {}
                meta.update({
                    "bulletin_id": b_id,
                    "revision": rev,
                    "content_hash": c_hash,
                    "root_hash": r_hash,
                    "publisher_id": pub_id,
                    "signature_hex": sig,
                    "title": title,
                    "received_at": recv_at,
                    "verified_status": status,
                    "data_size": d_size,
                })
                if status == "verified_ed25519" and meta.get("signature_version") != 2:
                    meta["verified_status"] = "legacy_signature_unverified"
                meta["publisher_trust"] = "not_established"
                results.append(meta)
            return results
        finally:
            conn.close()

    def prune_display_bulletins(self, keep_last_n: int = 50) -> int:
        """
        Prune older records from the display bulletins table to bound storage size,
        while strictly leaving bulletin_watermarks intact to reject stale replays.
        """
        with self._bulletin_lock:
            if not self.db_path or not self.db_path.exists():
                to_delete = len(self._bulletins) - keep_last_n
                if to_delete > 0:
                    sorted_keys = sorted(
                        self._bulletins.keys(),
                        key=lambda k: self._bulletins[k].get("received_at", 0)
                    )
                    for k in sorted_keys[:to_delete]:
                        del self._bulletins[k]
                    return to_delete
                return 0

            conn = sqlite3.connect(str(self.db_path))
            try:
                conn.execute("BEGIN IMMEDIATE")
                cur = conn.cursor()
                cur.execute(
                    """
                    DELETE FROM bulletins WHERE (bulletin_id, revision) NOT IN (
                        SELECT bulletin_id, revision FROM bulletins
                        ORDER BY received_at DESC, revision DESC LIMIT ?
                    )
                    """,
                    (keep_last_n,),
                )
                deleted = cur.rowcount
                conn.commit()
                return deleted
            finally:
                conn.close()

    def get_bulletin_watermark(self, publisher_id: str, bulletin_id: str) -> dict[str, Any] | None:
        """
        Retrieve the durable watermark record for a given publisher and bulletin ID.
        """
        with self._bulletin_lock:
            if not self.db_path or not self.db_path.exists():
                wm = self._bulletin_watermarks.get((publisher_id, bulletin_id))
                return dict(wm) if wm else None

            conn = sqlite3.connect(str(self.db_path))
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT publisher_id, bulletin_id, max_revision, latest_content_hash, latest_root_hash, first_seen_at, last_seen_at, latest_title, updated_at
                    FROM bulletin_watermarks WHERE publisher_id = ? AND bulletin_id = ?
                    """,
                    (publisher_id, bulletin_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                pub, bid, max_rev, c_hash, r_hash, first_at, last_at, l_title, up_at = row
                return {
                    "publisher_id": pub,
                    "bulletin_id": bid,
                    "max_revision": max_rev,
                    "latest_content_hash": c_hash,
                    "latest_root_hash": r_hash,
                    "first_seen_at": first_at,
                    "last_seen_at": last_at,
                    "latest_title": l_title,
                    "updated_at": up_at,
                }
            finally:
                conn.close()


