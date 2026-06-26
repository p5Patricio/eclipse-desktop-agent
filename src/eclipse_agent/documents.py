"""Document Q&A (RAG) for Eclipse over local notes and PDFs.

The pipeline is deliberately dependency-light: documents are chunked, embedded
through an OpenAI-compatible embeddings endpoint (Ollama ``nomic-embed-text`` by
default), and stored in SQLite. Retrieval is brute-force cosine similarity with
numpy — no vector database needed at personal-corpus scale.

Embeddings are provider-agnostic and default to a local model, separate from the
chat provider, because some chat providers (DeepSeek) expose no embeddings. The
embedding function is injectable, so the whole pipeline is testable without a
running model.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from eclipse_agent.answer import AnswerResult, QuestionAnswerer

DEFAULT_EMBEDDING_BASE_URL = "http://localhost:11434/v1"
DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"
DEFAULT_EMBEDDING_API_KEY = "not-needed"

SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".rst", ".text"}
SUPPORTED_SUFFIXES = SUPPORTED_TEXT_SUFFIXES | {".pdf"}

EmbedFn = Callable[[Sequence[str]], list[list[float]]]

RAG_SYSTEM_PROMPT = (
    "You are Eclipse answering from the user's own documents. Use ONLY the provided "
    "context to answer in one to three sentences, in the same language as the question. "
    "The answer is spoken aloud, so do not use markdown, lists, or code blocks. If the "
    "context does not contain the answer, say you could not find it in their documents."
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


# --- embeddings ----------------------------------------------------------


@dataclass(frozen=True)
class EmbeddingConfig:
    """Where to reach the OpenAI-compatible embeddings endpoint."""

    base_url: str = DEFAULT_EMBEDDING_BASE_URL
    model: str = DEFAULT_EMBEDDING_MODEL
    api_key: str = DEFAULT_EMBEDDING_API_KEY
    timeout_seconds: float = 30.0


def build_embedding_config_from_env() -> EmbeddingConfig:
    """Resolve the embedding endpoint from env, defaulting to local Ollama."""

    base_url = (
        os.environ.get("ECLIPSE_EMBED_BASE_URL")
        or os.environ.get("ECLIPSE_LLM_BASE_URL")
        or DEFAULT_EMBEDDING_BASE_URL
    )
    model = os.environ.get("ECLIPSE_EMBED_MODEL", DEFAULT_EMBEDDING_MODEL)
    api_key = (
        os.environ.get("ECLIPSE_EMBED_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or DEFAULT_EMBEDDING_API_KEY
    )
    return EmbeddingConfig(base_url=base_url, model=model, api_key=api_key)


class EmbeddingClient:
    """Embed text through an OpenAI-compatible embeddings endpoint."""

    def __init__(
        self,
        config: EmbeddingConfig | None = None,
        *,
        client: object | None = None,
    ) -> None:
        self.config = config or build_embedding_config_from_env()
        self._client = client

    @property
    def client(self) -> object:
        if self._client is None:
            try:
                from openai import OpenAI
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "The official 'openai' package is required to embed documents."
                ) from exc
            self._client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
            )
        return self._client

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.embeddings.create(  # type: ignore[attr-defined]
            model=self.config.model,
            input=list(texts),
        )
        return [list(item.embedding) for item in response.data]


# --- chunking and reading ------------------------------------------------


def chunk_text(text: str, *, size: int = 800, overlap: int = 150) -> list[str]:
    """Split text into ~``size``-char chunks with a small word overlap."""

    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for word in words:
        current.append(word)
        current_len += len(word) + 1
        if current_len >= size:
            chunks.append(" ".join(current))
            current, current_len = _overlap_tail(current, overlap)
    if current and (not chunks or " ".join(current) != chunks[-1]):
        chunks.append(" ".join(current))
    return chunks


def _overlap_tail(words: list[str], overlap: int) -> tuple[list[str], int]:
    tail: list[str] = []
    length = 0
    for word in reversed(words):
        if length >= overlap:
            break
        tail.insert(0, word)
        length += len(word) + 1
    return tail, length


def read_document(path: str | Path) -> str:
    """Read a supported document into plain text."""

    resolved = Path(path)
    suffix = resolved.suffix.casefold()
    if suffix in SUPPORTED_TEXT_SUFFIXES:
        return resolved.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        return _read_pdf(resolved)
    raise ValueError(f"Unsupported document type: {suffix or '<none>'}")


def _read_pdf(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Reading PDFs needs the 'documents' extra: pip install -e \".[documents]\"."
        ) from exc
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


# --- store ---------------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class DocumentChunk:
    """One embedded chunk of a source document."""

    source: str
    chunk_index: int
    text: str
    embedding: np.ndarray
    id: int | None = None


@dataclass(frozen=True)
class RetrievedChunk:
    """A chunk retrieved for a query, with its similarity score."""

    chunk: DocumentChunk
    score: float


class DocumentStore:
    """SQLite-backed store of embedded document chunks."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_document_store_path()
        self._initialize()

    def add_chunk(
        self, source: str, chunk_index: int, text: str, embedding: Sequence[float]
    ) -> None:
        vector = np.asarray(embedding, dtype=np.float32)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO chunks (source, chunk_index, text, embedding, dim, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source,
                    chunk_index,
                    text,
                    vector.tobytes(),
                    int(vector.size),
                    _to_iso(_utc_now()),
                ),
            )

    def all_chunks(self) -> tuple[DocumentChunk, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM chunks ORDER BY id ASC").fetchall()
        return tuple(_row_to_chunk(row) for row in rows)

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])

    def sources(self) -> tuple[tuple[str, int], ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT source, COUNT(*) AS n FROM chunks GROUP BY source ORDER BY source"
            ).fetchall()
        return tuple((str(row["source"]), int(row["n"])) for row in rows)

    def remove_source(self, source: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM chunks WHERE source = ?", (source,))
            return int(cursor.rowcount)

    def clear(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM chunks")
            return int(cursor.rowcount)

    def _initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    embedding BLOB NOT NULL,
                    dim INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


# --- ingest and retrieve -------------------------------------------------


@dataclass(frozen=True)
class IngestResult:
    """Outcome of ingesting one or more documents."""

    success: bool
    files: tuple[str, ...]
    chunks_added: int
    message: str


def ingest_path(
    path: str | Path,
    store: DocumentStore,
    embed: EmbedFn,
    *,
    replace: bool = True,
) -> IngestResult:
    """Read, chunk, embed, and store a file or every document in a directory."""

    root = Path(path).expanduser()
    files = _collect_files(root)
    if not files:
        return IngestResult(False, (), 0, f"No supported documents found at {root}.")

    ingested: list[str] = []
    total = 0
    for file in files:
        source = str(file)
        try:
            text = read_document(file)
        except (ValueError, RuntimeError, OSError) as exc:
            return IngestResult(False, tuple(ingested), total, str(exc))
        chunks = chunk_text(text)
        if not chunks:
            continue
        try:
            vectors = embed(chunks)
        except Exception as exc:  # noqa: BLE001
            return IngestResult(
                False, tuple(ingested), total, f"No pude generar embeddings: {exc}"
            )
        if replace:
            store.remove_source(source)
        for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
            store.add_chunk(source, index, chunk, vector)
        total += len(chunks)
        ingested.append(source)
    return IngestResult(
        True, tuple(ingested), total, f"Ingested {total} chunks from {len(ingested)} file(s)."
    )


def retrieve(
    query: str,
    store: DocumentStore,
    embed: EmbedFn,
    *,
    top_k: int = 4,
) -> tuple[RetrievedChunk, ...]:
    """Return the ``top_k`` chunks most similar to the query."""

    chunks = store.all_chunks()
    if not chunks:
        return ()
    query_vector = np.asarray(embed([query])[0], dtype=np.float32)
    scored = [
        RetrievedChunk(chunk=chunk, score=_cosine(query_vector, chunk.embedding))
        for chunk in chunks
    ]
    scored.sort(key=lambda item: item.score, reverse=True)
    return tuple(scored[:top_k])


@dataclass(frozen=True)
class DocumentAnswerResult:
    """Result of answering a question from stored documents."""

    success: bool
    query: str
    answer: str
    message: str
    sources: tuple[str, ...] = field(default_factory=tuple)


def answer_from_documents(
    query: str,
    store: DocumentStore,
    *,
    embed: EmbedFn | None = None,
    answerer: QuestionAnswerer | None = None,
    top_k: int = 4,
) -> DocumentAnswerResult:
    """Retrieve context from the store and answer the query grounded in it."""

    normalized = " ".join(query.strip().split())
    if not normalized:
        return DocumentAnswerResult(False, query, "", "Tell me what to look up.")
    embed_fn = embed or EmbeddingClient().embed
    try:
        retrieved = retrieve(normalized, store, embed_fn, top_k=top_k)
    except Exception as exc:  # noqa: BLE001
        return DocumentAnswerResult(
            False, normalized, "", f"No pude consultar tus documentos: {exc}"
        )
    if not retrieved:
        return DocumentAnswerResult(
            False, normalized, "", "Todavía no tengo documentos cargados."
        )
    context = "\n\n".join(f"[{Path(item.chunk.source).name}] {item.chunk.text}" for item in retrieved)
    resolver = answerer or QuestionAnswerer(system_prompt=RAG_SYSTEM_PROMPT)
    answer = resolver.answer(f"Context:\n{context}\n\nQuestion: {normalized}")
    sources = tuple(dict.fromkeys(Path(item.chunk.source).name for item in retrieved))
    return DocumentAnswerResult(answer.success, normalized, answer.answer, answer.message, sources)


# --- rendering and helpers -----------------------------------------------


def render_ingest_result(result: IngestResult) -> str:
    return result.message


def render_document_sources(sources: Iterable[tuple[str, int]]) -> str:
    ordered = tuple(sources)
    if not ordered:
        return "No documents ingested yet."
    lines = ["Ingested documents:"]
    for source, count in ordered:
        lines.append(f"- {Path(source).name}: {count} chunks")
    return "\n".join(lines)


def render_document_answer(result: DocumentAnswerResult) -> str:
    if not result.success:
        return f"Document answer [failed]: {result.message}"
    suffix = f" (sources: {', '.join(result.sources)})" if result.sources else ""
    return f"Document answer: {result.answer}{suffix}"


def default_document_store_path() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    return root / "eclipse-agent" / "documents.sqlite3"


def _collect_files(root: Path) -> tuple[Path, ...]:
    if root.is_file():
        return (root,) if root.suffix.casefold() in SUPPORTED_SUFFIXES else ()
    if not root.exists():
        return ()
    found = [
        path
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES
    ]
    return tuple(found)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0.0:
        return 0.0
    return float(np.dot(a, b) / denom)


def _row_to_chunk(row: sqlite3.Row) -> DocumentChunk:
    return DocumentChunk(
        id=int(row["id"]),
        source=str(row["source"]),
        chunk_index=int(row["chunk_index"]),
        text=str(row["text"]),
        embedding=np.frombuffer(row["embedding"], dtype=np.float32),
    )


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


__all__ = [
    "AnswerResult",
    "DocumentAnswerResult",
    "DocumentChunk",
    "DocumentStore",
    "EmbeddingClient",
    "EmbeddingConfig",
    "IngestResult",
    "RetrievedChunk",
    "answer_from_documents",
    "build_embedding_config_from_env",
    "chunk_text",
    "default_document_store_path",
    "ingest_path",
    "read_document",
    "render_document_answer",
    "render_document_sources",
    "render_ingest_result",
    "retrieve",
]
