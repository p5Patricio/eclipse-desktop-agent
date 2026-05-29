# Eclipse Desktop Agent

Eclipse es un asistente personal de escritorio, siempre disponible en segundo plano, capaz de escuchar una frase de activación local, observar eventos del sistema, entender contexto, preparar acciones, pedir confirmación y ejecutar tareas reales con seguridad.

> Objetivo: Eclipse debe sentirse como un asistente tipo Jarvis/Alexa: permanece activo como daemon local, despierta cuando digas **"Eclipse"**, puede avisarte proactivamente de eventos permitidos y actúa como copiloto confiable.

## Quick path

1. Leer [`docs/DEVELOPMENT_PLAN.md`](docs/DEVELOPMENT_PLAN.md) para entender el plan por fases.
2. Revisar [`docs/MODEL_AND_VOICE_STRATEGY.md`](docs/MODEL_AND_VOICE_STRATEGY.md) para mantener Eclipse free-first.
3. Revisar [`docs/SECURITY.md`](docs/SECURITY.md) antes de implementar automatización real.
4. Usar [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) como guía técnica.
5. Revisar [`docs/ALWAYS_ON_RUNTIME.md`](docs/ALWAYS_ON_RUNTIME.md) para activación y recursos.
6. Revisar [`docs/MULTI_ACTION_ORCHESTRATION.md`](docs/MULTI_ACTION_ORCHESTRATION.md) para instrucciones con varias acciones.
7. Revisar [`docs/TOOL_ROUTER_AND_DESKTOP_LAUNCHER.md`](docs/TOOL_ROUTER_AND_DESKTOP_LAUNCHER.md) para ruteo de tools y apps `.desktop`.
8. Revisar [`docs/BROWSER_AUTOMATION_ADAPTER.md`](docs/BROWSER_AUTOMATION_ADAPTER.md) para la integración inicial con `agent-browser`.
9. Revisar [`docs/CAPABILITY_ROADMAP.md`](docs/CAPABILITY_ROADMAP.md) para funciones pendientes.
10. Revisar [`docs/VOICE_AND_NATIVE_CONTROL.md`](docs/VOICE_AND_NATIVE_CONTROL.md) para voz local y control Fedora/KDE.
11. Revisar [`docs/NOTIFICATIONS_AND_DESKTOP_CONTROL.md`](docs/NOTIFICATIONS_AND_DESKTOP_CONTROL.md) para el flujo de notificaciones y apps nativas en Fedora/KDE.
12. Revisar [`docs/CODING_AGENT_BRIDGE.md`](docs/CODING_AGENT_BRIDGE.md) para Claude Code/Gemini/Codex.
13. Evaluar [`docs/AGENT_BROWSER_EVALUATION.md`](docs/AGENT_BROWSER_EVALUATION.md) para automatización web.
14. Evaluar OpenClaw con [`docs/OPENCLAW_STRATEGY.md`](docs/OPENCLAW_STRATEGY.md), sin convertirlo todavía en dependencia crítica.

## Principios del proyecto

| Principio | Decisión |
|---|---|
| Local-first | Eclipse debe correr principalmente en la computadora del usuario. |
| Always-on responsable | El daemon puede estar activo, pero no debe transcribir todo 24/7 por defecto. |
| Safety-first | Acciones sensibles requieren confirmación humana. |
| Draft-first | Al inicio Eclipse prepara borradores; no envía ni modifica sin permiso. |
| Provider-agnostic | OpenAI, Claude, Gemini y modelos locales deben poder intercambiarse. |
| Auditabilidad | Toda acción importante debe quedar registrada. |
| Plugins controlados | Las capacidades se agregan por herramientas con permisos explícitos. |

## Alcance inicial

El MVP no busca autonomía total. Busca demostrar este flujo:

```txt
Always-on daemon
  -> wake word local / eventos permitidos
  -> transcripción
  -> análisis de pantalla
  -> razonamiento del agente
  -> acción segura o borrador
  -> confirmación humana
  -> respuesta hablada
  -> memoria/log
```

## Estructura inicial

```txt
src/eclipse_agent/          Núcleo Python inicial
  activation.py             Política de activación always-on/wake-word
  browser_automation.py     Adapter inicial para agent-browser
  coding_agents.py          Registro y prompt contract para Claude/Gemini/Codex
  desktop_apps.py           Descubrimiento y lanzamiento seguro de apps .desktop
  fedora_control.py         Scaffold de control nativo Fedora/KDE
  main.py                   CLI placeholder para validar el paquete
  notifications.py          Core de notificaciones, reglas foco/juego y SQLite
  planner.py                Descomposición de instrucciones multi-acción
  resources.py              Estimaciones de recursos por modo de activación
  runtime_diagnostics.py    Diagnósticos de dependencias locales
  config.py                 Configuración base
  safety.py                 Modelo inicial de política de seguridad
  tool_router.py            Ruteo de acciones planeadas a tools locales
  voice.py                  TTS local y facade STT
docs/                       Plan, arquitectura, seguridad y OpenClaw
  adr/                      Decisiones arquitectónicas
```

## Estado

Proyecto entrando a fase **1: daemon always-on + voz mínima**.

## CLI inicial

```bash
PYTHONPATH=src python -m eclipse_agent status
PYTHONPATH=src python -m eclipse_agent diagnostics
PYTHONPATH=src python -m eclipse_agent say --text "Hola, soy Eclipse."
PYTHONPATH=src venv/bin/python -m eclipse_agent listen --seconds 3
PYTHONPATH=src python -m eclipse_agent resource-plan
PYTHONPATH=src python -m eclipse_agent plan \
  --instruction "Reproduce El lado oscuro en YouTube Music, también abre Instagram"
PYTHONPATH=src python -m eclipse_agent route-plan \
  --instruction "Reproduce El lado oscuro en YouTube Music, también abre Instagram"
PYTHONPATH=src python -m eclipse_agent browser-snapshot --url https://example.com
PYTHONPATH=src python -m eclipse_agent browser-action \
  --kind fill \
  --selector @e2 \
  --text "mensaje borrador" \
  --confirmed
PYTHONPATH=src python -m eclipse_agent fedora-open --app "YouTube Music"
PYTHONPATH=src python -m eclipse_agent coding-prompt \
  --agent "Claude Code" \
  --project /ruta/al/proyecto \
  --idea "Implementa esta idea..."
PYTHONPATH=src python -m eclipse_agent notifications-mode --mode game --minutes 60
PYTHONPATH=src python -m eclipse_agent notifications-mute --app Instagram --app Messenger
PYTHONPATH=src python -m eclipse_agent notifications-ingest \
  --app "Google Chrome" \
  --summary "Instagram" \
  --body "Nuevo mensaje" \
  --source-window "Instagram - Google Chrome"
PYTHONPATH=src python -m eclipse_agent notifications-summary --mark-announced
PYTHONPATH=src python -m eclipse_agent notifications-dbus-command
PYTHONPATH=src python -m eclipse_agent notifications-listen --seconds 30
PYTHONPATH=src python -m eclipse_agent notifications-intent \
  --text "Eclipse, modo juego por una hora"
PYTHONPATH=src python -m eclipse_agent notifications-reply-draft \
  --event-id EVENT_ID \
  --message "Ahorita entro"
PYTHONPATH=src python -m eclipse_agent notifications-reply-draft \
  --event-id EVENT_ID \
  --audio-path /tmp/eclipse-reply.wav
PYTHONPATH=src python -m eclipse_agent notifications-reply-draft \
  --event-id EVENT_ID \
  --message "Ahorita entro" \
  --snapshot-json /tmp/instagram-snapshot.json \
  --auto-select \
  --confirmed
PYTHONPATH=src python -m eclipse_agent notifications-service --action render
PYTHONPATH=src python -m eclipse_agent notifications-service --action install
```

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
