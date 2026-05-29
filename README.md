# Eclipse Desktop Agent

Eclipse es un asistente personal de escritorio, siempre disponible en segundo plano, capaz de escuchar una frase de activación local, observar eventos del sistema, entender contexto, preparar acciones, pedir confirmación y ejecutar tareas reales con seguridad.

> Objetivo: Eclipse debe sentirse como un asistente tipo Jarvis/Alexa: permanece activo como daemon local, despierta cuando digas **"Eclipse"**, puede avisarte proactivamente de eventos permitidos y actúa como copiloto confiable.

## Latest operational upgrades

Eclipse now includes two production-oriented improvements:

### Custom wake word for "Eclipse"

The wake-word runtime now expects a custom openwakeword model at:

```txt
models/eclipse.onnx
```

Generate it with:

```bash
python scripts/generate_wakeword.py --dry-run
python scripts/generate_wakeword.py
```

The generator writes a training config under `.wakeword-training/eclipse/` and
delegates to `openwakeword.train`. It requires the usual training assets:

- a Piper sample generator checkout,
- background audio clips,
- room impulse response clips,
- a false-positive validation `.npy` file,
- precomputed openwakeword feature files for training.

`OpenWakeWordTrigger` now loads `models/eclipse.onnx` by default and emits a
clear error if the model is missing.

### Dynamic screenshot vision routing

Eclipse can now analyze screenshots through a local vision model only when
vision is required. Text planning continues to use `qwen2.5:7b`, but screenshot
actions dynamically request `qwen2-vl:7b` through Ollama's OpenAI-compatible
endpoint.

When a screenshot action returns an image path, Eclipse:

1. reads the image from disk,
2. base64-encodes it,
3. sends an OpenAI-compatible multimodal payload,
4. requests `qwen2-vl:7b` only for that call.

If the vision model is missing, Eclipse returns a clear error message and tells
you to pull it with:

```bash
ollama pull qwen2-vl:7b
```

The setup script now pulls both the text and vision models automatically.

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
15. Generate the custom wake-word model with [`scripts/generate_wakeword.py`](scripts/generate_wakeword.py) before enabling efficient wake mode on a fresh machine.
16. Run [`scripts/setup_local_llm.sh`](scripts/setup_local_llm.sh) to install Ollama and pull both `qwen2.5:7b` and `qwen2-vl:7b`.

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
| Wake-word custom | Eclipse should use a phrase-specific openwakeword model for the word "Eclipse". |
| Vision on demand | Screenshot analysis should load the vision model only when visual input is required. |

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
  models/                   Wake-word models generated locally (e.g. eclipse.onnx)
  resources.py              Estimaciones de recursos por modo de activación
  runtime_diagnostics.py    Diagnósticos de dependencias locales
  config.py                 Configuración base
  safety.py                 Modelo inicial de política de seguridad
  tool_router.py            Ruteo de acciones planeadas a tools locales
  voice.py                  TTS local y facade STT
  wake_runtime.py           Loop wake/listen/respond acotado para pruebas reales
docs/                       Plan, arquitectura, seguridad y OpenClaw
  adr/                      Decisiones arquitectónicas
scripts/                    Helpers de setup y generación local de modelos
```

## Estado

Proyecto entrando a fase **1: daemon always-on + voz mínima**.
The current implementation also supports:

- custom wake-word training for `Eclipse`,
- dynamic screenshot routing to a local vision model,
- Wayland-native capture and typing scaffolding,
- local Ollama text + vision setup.

## CLI inicial

```bash
PYTHONPATH=src python -m eclipse_agent status
PYTHONPATH=src python -m eclipse_agent diagnostics
PYTHONPATH=src python -m eclipse_agent smoke-plan
PYTHONPATH=src python -m eclipse_agent smoke-simulate
PYTHONPATH=src python -m eclipse_agent say --text "Hola, soy Eclipse."
PYTHONPATH=src venv/bin/python -m eclipse_agent listen --seconds 3
PYTHONPATH=src venv/bin/python -m eclipse_agent wake-command \
  --text "Eclipse, dime qué llegó"
PYTHONPATH=src venv/bin/python -m eclipse_agent wake-loop --iterations 1
PYTHONPATH=src venv/bin/python -m eclipse_agent wake-loop \
  --iterations 1 \
  --execute
PYTHONPATH=src python scripts/generate_wakeword.py --dry-run
PYTHONPATH=src python scripts/generate_wakeword.py
PYTHONPATH=src python -m eclipse_agent resource-plan
PYTHONPATH=src python -m eclipse_agent plan \
  --instruction "Reproduce El lado oscuro en YouTube Music, también abre Instagram"
PYTHONPATH=src python -m eclipse_agent route-plan \
  --instruction "Reproduce El lado oscuro en YouTube Music, también abre Instagram"
PYTHONPATH=src python -m eclipse_agent plan \
  --instruction "What is on my screen?"
PYTHONPATH=src python -m eclipse_agent route-plan \
  --instruction "What is on my screen?"
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
  --record-seconds 4 \
  --record-audio-path /tmp/eclipse-reply.wav
PYTHONPATH=src python -m eclipse_agent notifications-reply-draft \
  --event-id EVENT_ID \
  --message "Ahorita entro" \
  --snapshot-json /tmp/instagram-snapshot.json \
  --auto-select \
  --confirmed
PYTHONPATH=src python -m eclipse_agent notifications-service --action render
PYTHONPATH=src python -m eclipse_agent notifications-service --action install
PYTHONPATH=src python -m eclipse_agent notifications-mark \
  --event-id EVENT_ID \
  --status replied \
  --confirmed
```

## Environment variables

The following environment variables are useful for local setup:

```bash
ECLIPSE_LOCAL_LLM_MODEL=qwen2.5:7b
ECLIPSE_LOCAL_VISION_MODEL=qwen2-vl:7b
ECLIPSE_LLM_BASE_URL=http://localhost:11434/v1
ECLIPSE_LLM_API_KEY=ollama
ECLIPSE_VISION_MODEL=qwen2-vl:7b
ECLIPSE_WAKEWORD_MODEL_PATH=/absolute/path/to/models/eclipse.onnx
ECLIPSE_MODELS_DIR=/absolute/path/to/models
```

## Recommended setup flow

1. Install Ollama and pull local models:
   ```bash
   bash scripts/setup_local_llm.sh
   ```
2. Generate the custom wake-word model:
   ```bash
   python scripts/generate_wakeword.py
   ```
3. Run Eclipse with efficient wake mode:
   ```bash
   PYTHONPATH=src python -m eclipse_agent wake-efficient --execute
   ```

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
