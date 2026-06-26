from eclipse_agent import main as main_module
from eclipse_agent.memory import (
    MemoryIntent,
    MemoryStore,
    parse_memory_request,
    render_memory_facts,
)
from eclipse_agent.planner import ActionKind, PlannedAction, create_action_plan
from eclipse_agent.safety import RiskLevel
from eclipse_agent.tool_router import (
    NativeMCPClient,
    ToolExecutionContext,
    ToolRouter,
)


# --- parsing -------------------------------------------------------------


def test_parse_mi_es_remember():
    request = parse_memory_request("mi nombre es Patricio")
    assert request.intent is MemoryIntent.REMEMBER
    assert request.key == "nombre"
    assert request.value == "Patricio"


def test_parse_remember_strips_eclipse_prefix_and_keeps_case():
    request = parse_memory_request("Eclipse, recordá que mi color favorito es el Azul")
    assert request.intent is MemoryIntent.REMEMBER
    assert request.key == "color favorito"
    assert request.value == "el Azul"


def test_parse_me_llamo_remember_as_nombre():
    request = parse_memory_request("me llamo Patricio")
    assert request.intent is MemoryIntent.REMEMBER
    assert request.key == "nombre"
    assert request.value == "Patricio"


def test_parse_english_my_is_remember():
    request = parse_memory_request("my city is Rosario")
    assert request.intent is MemoryIntent.REMEMBER
    assert request.key == "city"
    assert request.value == "Rosario"


def test_parse_como_me_llamo_recall_nombre():
    request = parse_memory_request("¿cómo me llamo?")
    assert request.intent is MemoryIntent.RECALL
    assert request.key == "nombre"


def test_parse_cual_es_mi_recall_key():
    request = parse_memory_request("¿cuál es mi color favorito?")
    assert request.intent is MemoryIntent.RECALL
    assert request.key == "color favorito"


def test_parse_recall_all_has_empty_key():
    request = parse_memory_request("¿qué sabés de mí?")
    assert request.intent is MemoryIntent.RECALL
    assert request.key == ""


def test_parse_non_memory_returns_none():
    assert parse_memory_request("abre Instagram en el navegador") is None
    assert parse_memory_request("¿qué hora es?") is None
    assert parse_memory_request("¿cuál es la capital de Francia?") is None


# --- store ---------------------------------------------------------------


def test_store_remember_recall_roundtrip(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite3")
    store.remember("nombre", "Patricio")

    fact = store.recall("Nombre")  # case-insensitive lookup
    assert fact is not None
    assert fact.value == "Patricio"


def test_store_remember_upserts_value(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite3")
    first = store.remember("ciudad", "Rosario")
    second = store.remember("ciudad", "Buenos Aires")

    assert store.recall("ciudad").value == "Buenos Aires"
    assert len(store.list_all()) == 1
    assert second.created_at == first.created_at  # created_at preserved on update


def test_store_search_matches_key_or_value(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite3")
    store.remember("color favorito", "azul")

    assert store.search("favorito")[0].value == "azul"
    assert store.search("azul")[0].key == "color favorito"


def test_store_forget_and_clear(tmp_path):
    store = MemoryStore(tmp_path / "m.sqlite3")
    store.remember("nombre", "Patricio")
    store.remember("ciudad", "Rosario")

    assert store.forget("nombre") is True
    assert store.forget("nombre") is False
    assert store.clear() == 1


def test_render_memory_facts_empty():
    assert "No remembered facts" in render_memory_facts(())


# --- planner routing -----------------------------------------------------


def test_plans_statement_as_remember_fact():
    plan = create_action_plan("Eclipse, mi nombre es Patricio")

    action = plan.actions[0]
    assert action.kind is ActionKind.REMEMBER_FACT
    assert action.tool_name == "native.remember_fact"
    assert action.parameters["memory_key"] == "nombre"
    assert action.parameters["memory_value"] == "Patricio"


def test_recall_question_routes_to_memory_not_answer():
    # Regression: "¿cómo me llamo?" is a question, but must hit memory recall
    # before the generic answer-question rule.
    plan = create_action_plan("Eclipse, ¿cómo me llamo?")

    action = plan.actions[0]
    assert action.kind is ActionKind.RECALL_MEMORY
    assert action.tool_name == "native.recall_memory"
    assert action.parameters["memory_key"] == "nombre"


def test_general_question_still_routes_to_answer():
    plan = create_action_plan("Eclipse, ¿cuál es la capital de Francia?")
    assert plan.actions[0].kind is ActionKind.ANSWER_QUESTION


# --- native tools --------------------------------------------------------


def _route(action: PlannedAction):
    return ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action, ToolExecutionContext(dry_run=False)
    )


def test_native_remember_fact_stores_and_confirms(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    action = PlannedAction(
        id="mem-1",
        kind=ActionKind.REMEMBER_FACT,
        description="Remember a fact.",
        risk_level=RiskLevel.LOW,
        target="nombre",
        parameters={"memory_key": "nombre", "memory_value": "Patricio"},
        tool_name="native.remember_fact",
    )

    result = _route(action)

    assert result.success is True
    assert result.structured_content["user_facts"]["spoken"] == "Listo, lo voy a recordar."
    assert MemoryStore().recall("nombre").value == "Patricio"


def test_native_recall_memory_speaks_value(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    MemoryStore().remember("nombre", "Patricio")

    action = PlannedAction(
        id="mem-2",
        kind=ActionKind.RECALL_MEMORY,
        description="Recall a fact.",
        risk_level=RiskLevel.LOW,
        target="nombre",
        parameters={"memory_key": "nombre"},
        tool_name="native.recall_memory",
    )

    result = _route(action)

    assert result.success is True
    assert result.structured_content["user_facts"]["spoken"] == "Te llamás Patricio."


def test_native_recall_unknown_is_graceful(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    action = PlannedAction(
        id="mem-3",
        kind=ActionKind.RECALL_MEMORY,
        description="Recall a fact.",
        risk_level=RiskLevel.LOW,
        target="apodo",
        parameters={"memory_key": "apodo"},
        tool_name="native.recall_memory",
    )

    result = _route(action)

    assert result.success is True
    assert "apodo" in result.structured_content["user_facts"]["spoken"]


# --- CLI -----------------------------------------------------------------


def test_cli_remember_phrase_then_list(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert main_module.main(["remember", "--text", "mi nombre es Patricio"]) == 0
    assert "nombre: Patricio" in capsys.readouterr().out

    assert main_module.main(["memory-list"]) == 0
    assert "nombre: Patricio" in capsys.readouterr().out


def test_cli_remember_explicit_key_value(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert main_module.main(["remember", "--key", "ciudad", "--value", "Rosario"]) == 0
    assert main_module.main(["memory-recall", "--key", "ciudad"]) == 0
    assert "ciudad: Rosario" in capsys.readouterr().out


def test_cli_memory_forget(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    main_module.main(["remember", "--key", "nombre", "--value", "Patricio"])
    capsys.readouterr()

    assert main_module.main(["memory-forget", "--key", "nombre"]) == 0
    assert "Forgot nombre" in capsys.readouterr().out
    assert main_module.main(["memory-forget", "--key", "nombre"]) == 1
