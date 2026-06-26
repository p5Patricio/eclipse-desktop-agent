from datetime import UTC, datetime, timedelta

from eclipse_agent import main as main_module
from eclipse_agent.planner import ActionKind, PlannedAction, create_action_plan
from eclipse_agent.routines import (
    RoutineAction,
    RoutineStore,
    ScheduleKind,
    compute_next_run,
    fire_due_routines,
    parse_routine_request,
    render_routines,
)
from eclipse_agent.safety import RiskLevel
from eclipse_agent.tool_router import NativeMCPClient, ToolExecutionContext, ToolRouter


# --- parsing -------------------------------------------------------------


def test_parse_daily_morning_defaults_to_eight():
    request = parse_routine_request("cada mañana decime el resumen")
    assert request is not None
    assert request.schedule_kind is ScheduleKind.DAILY
    assert request.schedule_value == "08:00"
    assert request.message == "el resumen"
    assert request.action is RoutineAction.SAY


def test_parse_daily_explicit_time():
    request = parse_routine_request("Eclipse, todos los días a las 7:30 decime que estudie")
    assert request.schedule_kind is ScheduleKind.DAILY
    assert request.schedule_value == "07:30"
    assert request.message == "estudie"


def test_parse_daily_evening_adds_twelve_hours():
    request = parse_routine_request("cada día a las 8 de la noche decime relajate")
    assert request.schedule_value == "20:00"


def test_parse_interval():
    request = parse_routine_request("cada 10 minutos recordame tomar agua")
    assert request.schedule_kind is ScheduleKind.INTERVAL
    assert request.schedule_value == "600"
    assert request.message == "tomar agua"


def test_parse_non_routine_returns_none():
    assert parse_routine_request("recordame en 10 minutos que saque la pizza") is None
    assert parse_routine_request("abre Instagram en el navegador") is None


# --- next run ------------------------------------------------------------


def test_compute_next_run_interval_adds_seconds():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert compute_next_run(ScheduleKind.INTERVAL, "600", now=now) == now + timedelta(seconds=600)


def test_compute_next_run_daily_is_future_local_time():
    now = datetime.now(UTC)
    nxt = compute_next_run(ScheduleKind.DAILY, "08:00", now=now)
    assert nxt > now
    local = nxt.astimezone()
    assert (local.hour, local.minute) == (8, 0)


# --- store ---------------------------------------------------------------


def test_store_add_auto_names_and_lists(tmp_path):
    store = RoutineStore(tmp_path / "r.sqlite3")
    first = store.add("el resumen", ScheduleKind.DAILY, "08:00")
    second = store.add("tomá agua", ScheduleKind.INTERVAL, "3600")

    assert first.name == "rutina-1"
    assert second.name == "rutina-2"
    assert len(store.list_all()) == 2


def test_store_add_upserts_by_name(tmp_path):
    store = RoutineStore(tmp_path / "r.sqlite3")
    store.add("uno", ScheduleKind.INTERVAL, "60", name="agua")
    store.add("dos", ScheduleKind.INTERVAL, "120", name="agua")

    routines = store.list_all()
    assert len(routines) == 1
    assert routines[0].message == "dos"


def test_store_remove_and_clear(tmp_path):
    store = RoutineStore(tmp_path / "r.sqlite3")
    store.add("uno", ScheduleKind.INTERVAL, "60", name="agua")

    assert store.remove("agua") is True
    assert store.remove("agua") is False
    store.add("dos", ScheduleKind.INTERVAL, "60")
    assert store.clear() == 1


def test_render_routines_empty():
    assert "No routines" in render_routines(())


# --- firing --------------------------------------------------------------


def test_fire_due_routines_speaks_and_reschedules(tmp_path):
    store = RoutineStore(tmp_path / "r.sqlite3")
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    store.add("tomá agua", ScheduleKind.INTERVAL, "60", now=base)  # next_run = base + 60s
    spoken: list[str] = []
    later = base + timedelta(seconds=120)

    fired = fire_due_routines(store, spoken.append, now=later)

    assert len(fired) == 1
    assert spoken == ["tomá agua"]
    assert store.due(later) == ()  # rescheduled into the future
    assert store.list_all()[0].next_run > later


def test_fire_ask_routine_uses_answer_callable(tmp_path):
    store = RoutineStore(tmp_path / "r.sqlite3")
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    store.add("dato curioso", ScheduleKind.INTERVAL, "60", action=RoutineAction.ASK, now=base)
    spoken: list[str] = []

    fire_due_routines(
        store,
        spoken.append,
        answer=lambda prompt: f"respuesta a {prompt}",
        now=base + timedelta(seconds=120),
    )

    assert spoken == ["respuesta a dato curioso"]


# --- planner routing -----------------------------------------------------


def test_plans_daily_phrase_as_add_routine():
    plan = create_action_plan("Eclipse, cada mañana decime el resumen")

    action = plan.actions[0]
    assert action.kind is ActionKind.ADD_ROUTINE
    assert action.tool_name == "native.add_routine"
    assert action.parameters["schedule_kind"] == "daily"
    assert action.parameters["routine_message"] == "el resumen"


def test_recurring_reminder_phrase_routes_to_routine_not_reminder():
    # Regression: "cada N minutos recordame X" recurs, so it must be a routine,
    # not a one-shot reminder, even though it contains a reminder token.
    plan = create_action_plan("Eclipse, cada 10 minutos recordame tomar agua")
    assert plan.actions[0].kind is ActionKind.ADD_ROUTINE


def test_one_shot_reminder_still_routes_to_reminder():
    plan = create_action_plan("Eclipse, recordame en 10 minutos que saque la pizza")
    assert plan.actions[0].kind is ActionKind.SET_REMINDER


# --- native tool ---------------------------------------------------------


def test_native_add_routine_stores_and_confirms(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    action = PlannedAction(
        id="rt-1",
        kind=ActionKind.ADD_ROUTINE,
        description="Add a routine.",
        risk_level=RiskLevel.LOW,
        target="routine",
        parameters={
            "routine_message": "el resumen",
            "routine_action": "say",
            "schedule_kind": "daily",
            "schedule_value": "08:00",
        },
        tool_name="native.add_routine",
    )

    result = ToolRouter(mcp_client=NativeMCPClient()).route_action(
        action, ToolExecutionContext(dry_run=False)
    )

    assert result.success is True
    assert "cada día" in result.structured_content["user_facts"]["spoken"]
    assert RoutineStore().list_all()[0].message == "el resumen"


# --- CLI -----------------------------------------------------------------


def test_cli_routine_add_phrase_and_list(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert main_module.main(["routine-add", "--text", "cada mañana decime el resumen"]) == 0
    assert "scheduled" in capsys.readouterr().out

    assert main_module.main(["routines-list"]) == 0
    assert "el resumen" in capsys.readouterr().out


def test_cli_routine_add_explicit_and_remove(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    assert main_module.main(
        ["routine-add", "--name", "agua", "--message", "tomá agua", "--every-seconds", "3600"]
    ) == 0
    capsys.readouterr()

    assert main_module.main(["routine-remove", "--name", "agua"]) == 0
    assert "Removed routine 'agua'" in capsys.readouterr().out
    assert main_module.main(["routine-remove", "--name", "agua"]) == 1


def test_cli_routines_check_fires_due(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    RoutineStore().add(
        "buenos días",
        ScheduleKind.INTERVAL,
        "60",
        now=datetime.now(UTC) - timedelta(seconds=120),
    )

    assert main_module.main(["routines-check"]) == 0
    assert "Fired:" in capsys.readouterr().out


# --- daemon poller -------------------------------------------------------


def test_wake_runtime_poll_fires_due_routines(tmp_path):
    from eclipse_agent.notifications import NotificationStore
    from eclipse_agent.wake_runtime import WakeRuntime

    spoken: list[tuple[str, bool]] = []

    class FakeTTS:
        def speak(self, text, *, dry_run=True):
            spoken.append((text, dry_run))

    store = RoutineStore(tmp_path / "r.sqlite3")
    store.add(
        "buenos días",
        ScheduleKind.INTERVAL,
        "60",
        now=datetime.now(UTC) - timedelta(seconds=120),
    )

    runtime = WakeRuntime(
        tts=FakeTTS(),
        store=NotificationStore(tmp_path / "n.sqlite3"),
        routine_store=store,
    )

    fired = runtime._poll_routines_once(dry_run=True)

    assert len(fired) == 1
    assert spoken and "buenos días" in spoken[0][0]
