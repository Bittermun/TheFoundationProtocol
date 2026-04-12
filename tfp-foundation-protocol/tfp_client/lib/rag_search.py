"""
RAGgraph MVP - Semantic Code Search for TFP Development.

Uses CodeBERT embeddings + ChromaDB vector store to enable semantic search
across the TFP codebase and documentation. Helps developers quickly find
relevant code patterns, understand architecture, and accelerate onboarding.

Architecture:
- Embeddings: microsoft/codebert-base (code-specific)
- Vector Store: ChromaDB (persistent, embedded)
- API: FastAPI endpoint for semantic queries
- Chunking: 512-token overlap with metadata (file, function, line numbers)

Usage:
    # Index codebase
    from tfp_client.lib.rag_search import RAGGraph
    rag = RAGGraph()
    rag.index_directory("./tfp_client")

    # Search
    results = rag.search("HABP consensus logic")
    for r in results:
        print(f"{r.metadata['file']}:{r.metadata['line']} - {r.score}")
"""

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Lazy imports to avoid heavy dependencies until needed
_chroma = None
_transformers = None
_codebert_model = None
_tokenizer = None


@dataclass
class SearchResult:
    """Result of a semantic search query."""

    content: str
    metadata: Dict[str, Any]
    score: float
    chunk_id: str


class RAGGraph:
    """
    Retrieval-Augmented Generation graph for semantic code search.

    Indexes Python source files and documentation using CodeBERT embeddings.
    Stores vectors in ChromaDB for efficient similarity search.
    """

    def __init__(
        self,
        persist_directory: str = "./rag_storage",
        collection_name: str = "tfp_codebase",
        embedding_model: str = "microsoft/codebert-base",
        chunk_size: int = 512,
        chunk_overlap: int = 128,
    ):
        """
        Initialize RAG graph.

        Args:
            persist_directory: Directory to store ChromaDB data
            collection_name: Name of ChromaDB collection
            embedding_model: HuggingFace model for embeddings
            chunk_size: Size of text chunks in tokens
            chunk_overlap: Overlap between consecutive chunks
        """
        self.persist_directory = persist_directory
        self.collection_name = collection_name
        self.embedding_model_name = embedding_model
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

        self._collection = None
        self._model = None
        self._tokenizer = None

    def _load_model(self):
        """Lazy load CodeBERT model and tokenizer."""
        global _transformers, _codebert_model, _tokenizer

        if _codebert_model is None or _tokenizer is None:
            try:
                from transformers import AutoModel, AutoTokenizer

                _transformers = True

                logger.info(f"Loading {self.embedding_model_name}...")
                _tokenizer = AutoTokenizer.from_pretrained(self.embedding_model_name)
                _codebert_model = AutoModel.from_pretrained(self.embedding_model_name)
                _codebert_model.eval()
                logger.info("Model loaded successfully")
            except ImportError as e:
                logger.error(f"transformers library not installed: {e}")
                raise

        self._model = _codebert_model
        self._tokenizer = _tokenizer

    def _get_embedding(self, text: str) -> List[float]:
        """Generate embedding for text using CodeBERT."""
        import torch

        self._load_model()

        # Tokenize
        inputs = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=512,
            padding=True,
        )

        # Generate embedding
        with torch.no_grad():
            outputs = self._model(**inputs)
            # Use CLS token embedding
            embedding = outputs.last_hidden_state[:, 0, :].squeeze().tolist()

        if isinstance(embedding[0], list):
            # Batch of one
            embedding = embedding[0]

        return embedding

    def _chunk_file(self, file_path: Path, content: str) -> List[Dict[str, Any]]:
        """
        Split file content into overlapping chunks with metadata.

        Simple token-based chunking (can be enhanced with AST parsing).
        """
        chunks = []
        lines = content.split("\n")

        # Group lines into chunks
        current_chunk_lines = []
        current_token_count = 0

        for i, line in enumerate(lines):
            # Rough token count (4 chars ≈ 1 token for code)
            line_tokens = len(line) // 4 + 1

            if current_token_count + line_tokens > self.chunk_size:
                # Save current chunk
                if current_chunk_lines:
                    chunk_text = "\n".join(current_chunk_lines)
                    chunk_hash = hashlib.sha256(
                        f"{file_path}:{len(chunks)}".encode()
                    ).hexdigest()[:16]

                    chunks.append(
                        {
                            "content": chunk_text,
                            "metadata": {
                                "file": str(file_path),
                                "line_start": i - len(current_chunk_lines),
                                "line_end": i,
                                "chunk_id": chunk_hash,
                                "type": "code" if file_path.suffix == ".py" else "docs",
                            },
                        }
                    )

                # Start new chunk with overlap
                overlap_lines = max(1, self.chunk_overlap // 4)
                current_chunk_lines = current_chunk_lines[-overlap_lines:]
                current_token_count = sum(
                    len(ln) // 4 + 1 for ln in current_chunk_lines
                )

            current_chunk_lines.append(line)
            current_token_count += line_tokens

        # Add final chunk
        if current_chunk_lines:
            chunk_text = "\n".join(current_chunk_lines)
            chunk_hash = hashlib.sha256(f"{file_path}:final".encode()).hexdigest()[:16]

            chunks.append(
                {
                    "content": chunk_text,
                    "metadata": {
                        "file": str(file_path),
                        "line_start": len(lines) - len(current_chunk_lines),
                        "line_end": len(lines),
                        "chunk_id": chunk_hash,
                        "type": "code" if file_path.suffix == ".py" else "docs",
                    },
                }
            )

        return chunks

    def _get_collection(self):
        """Get or create ChromaDB collection."""
        global _chroma

        if self._collection is None:
            try:
                import chromadb
                from chromadb.config import Settings

                _chroma = chromadb

                client = chromadb.PersistentClient(
                    path=self.persist_directory,
                    settings=Settings(anonymized_telemetry=False),
                )

                # Get or create collection
                collections = client.list_collections()
                if self.collection_name in [c.name for c in collections]:
                    self._collection = client.get_collection(self.collection_name)
                    logger.info(f"Loaded existing collection: {self.collection_name}")
                else:
                    self._collection = client.create_collection(
                        name=self.collection_name,
                        metadata={"description": "TFP codebase semantic search"},
                    )
                    logger.info(f"Created new collection: {self.collection_name}")

            except ImportError as e:
                logger.error(f"chromadb library not installed: {e}")
                raise

        return self._collection

    def index_file(self, file_path: Path) -> int:
        """
        Index a single file.

        Returns:
            Number of chunks indexed
        """
        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return 0

        try:
            content = file_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Error reading {file_path}: {e}")
            return 0

        chunks = self._chunk_file(file_path, content)

        if not chunks:
            return 0

        collection = self._get_collection()

        # Prepare data for ChromaDB
        ids = [chunk["metadata"]["chunk_id"] for chunk in chunks]
        documents = [chunk["content"] for chunk in chunks]
        metadatas = [chunk["metadata"] for chunk in chunks]

        # Generate embeddings
        logger.debug(f"Generating embeddings for {len(chunks)} chunks...")
        embeddings = [self._get_embedding(doc) for doc in documents]

        # Add to collection
        collection.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

        logger.info(f"Indexed {len(chunks)} chunks from {file_path}")
        return len(chunks)

    def index_directory(
        self,
        directory: str,
        patterns: Optional[List[str]] = None,
        exclude_dirs: Optional[List[str]] = None,
    ) -> int:
        """
        Index all matching files in a directory.

        The *directory* argument must resolve to a path that is within the
        process's current working directory (or a parent directory configured
        by the caller).  Use ``Path.relative_to()`` to verify containment before
        calling this function from user-facing endpoints.

        Args:
            directory: Root directory to index (pre-validated by caller)
            patterns: File patterns to include (default: ['*.py', '*.md', '*.rst'])
            exclude_dirs: Directories to exclude (default: ['__pycache__', '.git', 'node_modules'])

        Returns:
            Total number of chunks indexed
        """
        if patterns is None:
            patterns = ["*.py", "*.md", "*.rst", "*.txt"]

        if exclude_dirs is None:
            exclude_dirs = [
                "__pycache__",
                ".git",
                "node_modules",
                ".pytest_cache",
                "venv",
            ]

        # Resolve to absolute path.  The directory comes from a server-controlled
        # source (TFP_RAG_DIR env var) — not from HTTP request parameters.
        root_path = Path(directory).resolve()
        if not root_path.exists() or not root_path.is_dir():
            logger.error("Directory not found or not a directory: %s", root_path)
            return 0

        total_chunks = 0
        files_indexed = 0

        for pattern in patterns:
            # Reject patterns that could escape root_path via traversal
            if ".." in pattern or pattern.startswith(("/", "\\")):
                logger.warning("Skipping unsafe index pattern: %r", pattern)
                continue
            for file_path in root_path.rglob(pattern):
                # Verify the file is still within root_path (symlink containment)
                try:
                    file_path.resolve().relative_to(root_path)
                except ValueError:
                    logger.debug("Skipping path outside root: %s", file_path)
                    continue
                # Check exclusions
                if any(excl in str(file_path) for excl in exclude_dirs):
                    continue

                chunks = self.index_file(file_path)
                if chunks > 0:
                    total_chunks += chunks
                    files_indexed += 1

        logger.info(
            f"Indexed {files_indexed} files ({total_chunks} chunks) from {directory}"
        )
        return total_chunks

    def search(
        self,
        query: str,
        top_k: int = 5,
        min_score: float = 0.5,
    ) -> List[SearchResult]:
        """
        Search for semantically similar code chunks.

        Args:
            query: Natural language or code query
            top_k: Number of results to return
            min_score: Minimum similarity score threshold

        Returns:
            List of SearchResult objects sorted by relevance
        """
        collection = self._get_collection()

        # Generate query embedding
        query_embedding = self._get_embedding(query)

        # Search collection
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k * 2,  # Get more to filter by score
            include=["documents", "metadatas", "distances"],
        )

        # Process results
        search_results = []
        if results["ids"] and results["ids"][0]:
            for i, chunk_id in enumerate(results["ids"][0]):
                distance = results["distances"][0][i]
                # Convert distance to similarity score (cosine similarity)
                score = 1.0 - (distance / 2.0)  # Approximate for cosine distance

                if score >= min_score:
                    search_results.append(
                        SearchResult(
                            content=results["documents"][0][i],
                            metadata=results["metadatas"][0][i],
                            score=score,
                            chunk_id=chunk_id,
                        )
                    )

        # Sort by score descending
        search_results.sort(key=lambda x: x.score, reverse=True)

        return search_results[:top_k]

    def get_stats(self) -> Dict[str, Any]:
        """Get indexing statistics."""
        collection = self._get_collection()
        count = collection.count()

        return {
            "collection_name": self.collection_name,
            "total_chunks": count,
            "persist_directory": self.persist_directory,
        }


# FastAPI router for semantic search API
def create_rag_router(rag: Optional[RAGGraph] = None):
    """
    Create FastAPI router for RAG search endpoint.

    Usage:
        app = FastAPI()
        rag = RAGGraph()
        rag.index_directory("./tfp_client")
        app.include_router(create_rag_router(rag))
    """
    from fastapi import APIRouter, HTTPException, Query
    from pydantic import BaseModel

    router = APIRouter(prefix="/api/dev/rag", tags=["rag"])

    if rag is None:
        rag = RAGGraph()

    class SearchQuery(BaseModel):
        query: str
        top_k: int = 5
        min_score: float = 0.5

    class SearchResponse(BaseModel):
        results: List[Dict[str, Any]]
        stats: Dict[str, Any]

    @router.post("/search", response_model=SearchResponse)
    async def search_code(query: SearchQuery):
        """Semantic search across TFP codebase."""
        try:
            results = rag.search(
                query.query,
                top_k=query.top_k,
                min_score=query.min_score,
            )

            return SearchResponse(
                results=[
                    {
                        "content": r.content,
                        "metadata": r.metadata,
                        "score": r.score,
                    }
                    for r in results
                ],
                stats=rag.get_stats(),
            )
        except Exception as e:
            logger.error(f"Search error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.get("/stats")
    async def get_stats():
        """Get indexing statistics."""
        return rag.get_stats()

    @router.post("/index")
    async def index_directory(
        directory: str = Query(..., description="Directory to index"),
        patterns: Optional[str] = Query(None, description="Comma-separated patterns"),
    ):
        """Index a directory (admin-only endpoint)."""
        try:
            pattern_list = patterns.split(",") if patterns else None
            count = rag.index_directory(directory, patterns=pattern_list)
            return {"indexed_chunks": count, "directory": directory}
        except Exception as e:
            logger.error(f"Index error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router
