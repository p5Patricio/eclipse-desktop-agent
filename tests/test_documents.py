import numpy as np

from eclipse_agent import main as main_module
from eclipse_agent.answer import AnswerResult
from eclipse_agent.documents import (
    DocumentAnswerResult,
    DocumentStore,
    answer_from_documents,
    chunk_text,
    ingest_path,
    read_document,
    retrieve,
)
from eclipse_agent.planner import ActionKind, PlannedAction, create_action_plan
from eclipse_agent.safety import RiskLevel
from eclipse_agent.tool_router import NativeMCPClient, ToolExecutionContext, ToolRouter

_VOCAB = ("pizza", "horno", "python", "lenguaje", "eclipse", "asistente", "voz", "deploy")


def fake_embed(texts):
    """Deterministic bag-of-words embedder over a fixed vocabulary."""

    return [[float(text.casefold().count(word)) for word in _VOCAB] for text in texts]


class FakeAnswerer:
    def __init__(self) -> None:
        self.seen = ""

    def answer(self, text: str) -> AnswerResult:
        self.seen = text
        return AnswerResult(True, text, "respuesta basada en contexto", "ok")


# --- chunking and reading ------------------------------------------------


def test_chunk_text_splits_long_text_with_overlap():
    text = " ".join(f"palabra{i}" for i in range(100))
    chunks = chunk_text(text, size=120, overlap=30)
    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)


def test_chunk_text_short_text_is_single_chunk():
    assert chunk_text("hola mundo") == ["hola mundo"]
    assert chunk_text("   ") == []


def test_read_document_text_and_unsupported(tmp_path):
    note = tmp_path / "nota.md"
    note.write_text("contenido de prueba", encoding="utf-8")
    assert read_document(note) == "contenido de prueba"

    bad = tmp_path / "thing.xyz"
    bad.write_text("x", encoding="utf-8")
    try:
        read_document(bad)
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


# --- store ---------------------------------------------------------------


def test_store_add_and_roundtrip_embedding(tmp_path):
    store = DocumentStore(tmp_path / "d.sqlite3")
    store.add_chunk("nota.md", 0, "texto", [1.0, 0.0, 2.0])

    chunks = store.all_chunks()
    assert len(chunks) == 1
    assert isinstance(chunks[0].embedding, np.ndarray)
    assert list(chunks[0].embedding) == [1.0, 0.0, 2.0]


def test_store_sources_remove_and_clear(tmp_path):
    store = DocumentStore(tmp_path / "d.sqlite3")
    store.add_chunk("a.md", 0, "x", [1.0])
    store.add_chunk("a.md", 1, "y", [1.0])
    store.add_chunk("b.md", 0, "z", [1.0])

    assert store.sources() == (("a.md", 2), ("b.md", 1))
    assert store.remove_source("a.md") == 2
    assert store.clear() == 1


# --- ingest and retrieve -------------------------------------------------


def test_ingest_directory_populates_store(tmp_path):
    (tmp_path / "pizza.md").write_text("la pizza se hornea en el horno", encoding="utf-8")
    (tmp_path / "python.md").write_text("python es un lenguaje", encoding="utf-8")
    store = DocumentStore(tmp_path / "d.sqlite3")

    result = ingest_path(tmp_path, store, fake_embed)

    assert result.success is True
    assert result.chunks_added == 2
    assert store.count() == 2


def test_ingest_replace_does_not_duplicate(tmp_path):
    note = tmp_path / "n.md"
    note.write_text("python es un lenguaje", encoding="utf-8")
    store = DocumentStore(tmp_path / "d.sqlite3")

    ingest_path(note, store, fake_embed)
    ingest_path(note, store, fake_embed)

    assert store.count() == 1


def test_ingest_embed_failure_is_graceful(tmp_path):
    (tmp_path / "n.md").write_text("python lenguaje", encoding="utf-8")
    store = DocumentStore(tmp_path / "d.sqlite3")

    def boom(_texts):
        raise RuntimeError("ollama down")

    result = ingest_path(tmp_path, store, boom)
    assert result.success is False
    assert "embeddings" in result.message
    assert store.count() == 0


def test_retrieve_ranks_relevant_chunk_first(tmp_path):
    store = DocumentStore(tmp_path / "d.sqlite3")
    (tmp_path / "pizza.md").write_text("la pizza se hornea en el horno", encoding="utf-8")
    (tmp_path / "python.md").write_text("python es un lenguaje", encoding="utf-8")
    ingest_path(tmp_path, store, fake_embed)

    top = retrieve("quiero pizza del horno", store, fake_embed, top_k=1)
    assert len(top) == 1
    assert "pizza" in top[0].chunk.text


# --- grounded answer -----------------------------------------------------


def test_answer_from_documents_uses_retrieved_context(tmp_path):
    store = DocumentStore(tmp_path / "d.sqlite3")
    (tmp_path / "deploy.md").write_text("el deploy se hace con eclipse", encoding="utf-8")
    ingest_path(tmp_path, store, fake_embed)
    answerer = FakeAnswerer()

    result = answer_from_documents(
        "qué dije del deploy", store, embed=fake_embed, answerer=answerer
    )

    assert result.success is True
    assert "deploy" in answerer.seen  # retrieved context fed to the LLM
    assert result.sources == ("deploy.md",)


def test_answer_from_documents_empty_store_is_graceful(tmp_path):
    store = DocumentStore(tmp_path / "d.sqlite3")
    result = answer_from_documents("lo que sea", store, embed=fake_embed)
    assert result.success is False
    assert "documentos" in result.message


def test_answer_from_documents_embed_failure_is_graceful(tmp_path):
    store = DocumentStore(tmp_path / "d.sqlite3")
    (tmp_path / "n.md").write_text("python lenguaje", encoding="utf-8")
    ingest_path(tmp_path, store, fake_embed)

    def boom(_texts):
        raise RuntimeError("ollama down")

    result = answer_from_documents("algo", store, embed=boom)
    assert result.success is False
    assert "No pude consultar" in result.message


# --- planner -------------------------------------------------------------


def test_document_question_routes_to_query_documents():
    plan = create_action_plan("Eclipse, según mis notas qué dije del deploy")

    action = plan.actions[0]
    assert action.kind is ActionKind.QUERY_DOCUMENTS
    assert action.tool_name == "native.query_documents"


def test_plain_question_still_routes_to_answer():
    plan = create_action_plan("Eclipse, ¿cuál es la capital de Francia?")
    assert plan.actions[0].kind is ActionKind.ANSWER_QUESTION


# --- native tool ---------------------------------------------------------


def test_native_query_documents_speaks_answer(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    import eclipse_agent.documents as docs_mod

    monkeypatch.setattr(
        docs_mod,
        "answer_from_documents",
        lambda question, store, **kwargs: DocumentAnswerResult(
            True, question, "Dijiste que el deploy va los viernes.", "ok", ("deploy.md",)
        ),
    )

    action = PlannedAction(
        id="doc-1",
        kind=ActionKind.QUERY_DOCUMENTS,
        description="Query documents.",
        risk_level=RiskLevel.LOW,
        target="documents",
        parameters={"question": "qué dije del deploy"},
        tool_name="native.query_documents",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action, ToolExecutionContext(dry_run=False)
    )

    assert result.success is True
    assert "deploy va los viernes" in result.structured_content["user_facts"]["spoken"]


# --- CLI -----------------------------------------------------------------


def test_cli_docs_list_clear_and_ask(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert main_module.main(["docs-list"]) == 0
    assert "No documents" in capsys.readouterr().out

    assert main_module.main(["docs-clear"]) == 0
    assert "Cleared 0" in capsys.readouterr().out

    assert main_module.main(["docs-ask", "--query", "algo"]) == 1
    assert "failed" in capsys.readouterr().out
