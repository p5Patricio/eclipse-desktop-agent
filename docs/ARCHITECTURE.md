# Arquitectura de Eclipse

Eclipse es un asistente de escritorio modular para **Windows**. El núcleo no depende de un
solo proveedor de modelos ni de una sola herramienta de automatización: la voz corre
local, y el razonamiento se rutea a un proveedor configurable.

## Diagrama lógico

```txt
Input Layer
  - daemon always-on
  - wake word local (openwakeword)
  - notificaciones de Windows
  - modos de foco/juego
  - captura de pantalla
        |
        v
Perception Layer
  - speech-to-text (faster-whisper)
  - análisis de pantalla (visión local)
  - parser de notificaciones
  - filtro de privacidad (redacción de ventanas sensibles)
        |
        v
Agent Orchestrator
  - clasificación de intención
  - planificador híbrido (determinista + LLM)
  - chequeos de seguridad
  - reglas de notificaciones
        |
        v
Tool Executor
  - tool router (nativo + MCP)
  - automatización de navegador
  - bridge a agentes de código
  - control de escritorio (PAL de Windows)
        |
        v
Verification + Response
  - validación de resultado/captura
  - TTS (SAPI)
  - logs / memoria (SQLite)
```

## Módulos principales

| Módulo | Responsabilidad |
|---|---|
| `activation` | Política de daemon always-on y wake word |
| `voice` | STT (faster-whisper), TTS y wake-word trigger |
| `wake_runtime` | Loop wake → escuchar → razonar → responder |
| `planner` | Divide instrucciones compuestas en acciones; provider-agnostic |
| `tool_router` | Convierte `PlannedAction` en tools concretas con gates de seguridad |
| `browser_automation` | Abre/busca/snapshot en navegador vía `agent-browser` |
| `browser_ref_selector` | Elige refs semánticos del snapshot de accesibilidad por propósito |
| `media_playback` | Abre la búsqueda de una app de música (YouTube Music) en el navegador por defecto |
| `coding_agents` | Prepara prompts y abre Claude Code / Gemini / Codex |
| `notifications` | Captura, reglas de foco, resúmenes y borradores (SQLite) |
| `desktop_control` | Tipos de resultado neutrales para control de escritorio |
| `system_control` | Volumen, medios, bloqueo de pantalla y batería (teclas virtuales) |
| `clipboard` | Lee/escribe el portapapeles de Windows |
| `answer` | Responde preguntas con el proveedor LLM (resumen hablado) |
| `reminders` | Recordatorios y timers (SQLite), disparados por el daemon |
| `memory` | Memoria persistente de hechos y preferencias (SQLite) |
| `routines` | Rutinas proactivas recurrentes (SQLite), disparadas por el daemon |
| `documents` | Q&A (RAG) sobre notas/PDFs: embeddings + similitud coseno en SQLite |
| `email_inbox` | Lectura/resumen de bandeja y borradores por IMAP (read-only, nunca envía) |
| `calendar_agenda` | Lectura de la agenda desde iCal (.ics), con recurrencias expandidas (read-only) |
| `response_formatter` | Construye la respuesta hablada a partir del resultado de la acción |
| `pal/` | **Platform Abstraction Layer** de Windows: ventanas, input, captura, lanzador, notificaciones, voz, daemon |
| `safety/` | Política de riesgo y redacción de capturas |
| `audit` | Log auditable de cada acción ruteada (SQLite) |
| `killswitch` | Interruptor global persistido; pausa toda ejecución |
| `runtime_diagnostics` | Estado de dependencias locales (CLI `diagnostics`) |
| `telemetry` | Métricas de la capa de planificación (SQLite) |

## Platform Abstraction Layer (PAL)

Todo lo nativo de Windows pasa por interfaces en `pal/base.py`
(`WindowManager`, `InputSynthesizer`, `ScreenCapture`, `AppLauncher`,
`NotificationDaemon`, `TTSProvider`, `AudioRecorder`, `DaemonManager`,
`SystemController`).
`PlatformFactory` construye las implementaciones de `pal/windows/`. Esto mantiene el resto
del código desacoplado de detalles de plataforma y testeable por inyección de dependencias.

## Planificador y proveedores

El `HybridPlanner` usa primero reglas deterministas rápidas y cae a una capa LLM solo para
instrucciones que no reconoce. La capa LLM es **provider-agnostic**: DeepSeek, Ollama y
OpenAI hablan la misma API OpenAI-compatible, así que un proveedor es solo un preset de
datos (`LLMProvider`), no una jerarquía de clases.

| Proveedor | Endpoint | Structured output | Visión |
|---|---|---|---|
| `ollama` (default) | local | json_schema estricto | sí |
| `deepseek` | api.deepseek.com | json_object + schema en prompt | no |
| `openai` | api.openai.com | json_schema estricto | sí |

Se elige con `--provider` o `ECLIPSE_LLM_PROVIDER`. La visión de pantalla se mantiene local
(qwen2.5vl) porque DeepSeek no expone un modelo multimodal. Lo mismo aplica a los embeddings
para Q&A de documentos: corren por un modelo local (Ollama `nomic-embed-text`) por defecto,
configurable con `ECLIPSE_EMBED_MODEL` / `ECLIPSE_EMBED_BASE_URL`.

## Loop de ejecución

1. Recibir evento: wake word, texto o notificación.
2. Si es notificación, aplicar reglas de foco/silencio antes de hablar.
3. Clasificar intención y dividir instrucciones compuestas en `PlannedAction`.
4. Decidir si necesita observar la pantalla.
5. Rutear cada acción a una tool concreta.
6. Evaluar la política de seguridad.
7. Ejecutar la herramienta o pedir confirmación.
8. Verificar el resultado.
9. Responder por voz/texto.
10. Registrar el evento y la memoria permitida.

## Modos de operación

| Modo | Qué permite |
|---|---|
| `observe` | Solo ve/resume. No actúa. |
| `draft` | Prepara texto o pasos. No confirma. |
| `copilot` | Ejecuta acciones reversibles y pide confirmación en las sensibles. |
| `autonomous` | Solo para tareas allowlist de bajo riesgo. No usar al inicio. |

## Seguridad

- **Draft-first**: por defecto se preparan borradores, no se ejecuta.
- **Confirmación obligatoria** para acciones de impacto (input nativo, mensajes, agentes de
  código, borrado).
- **Redacción de pantalla**: las ventanas sensibles (bancos, gestores de contraseñas) se
  difuminan antes de analizar una captura.
- **Kill switch + audit log**: el `ToolRouter` consulta un interruptor global antes de
  ejecutar cualquier acción (lo pausa todo) y registra cada acción —intención, herramienta,
  riesgo y resultado— en un log auditable local.

Ver [`SECURITY.md`](SECURITY.md) para el detalle del modelo de seguridad.

## Agentes de codificación

Eclipse puede abrir un agente de programación externo solo bajo un flujo supervisado: el
usuario dicta una idea, Eclipse construye un prompt estructurado, pide confirmación de
agente + proyecto + prompt, y abre Claude Code / Gemini CLI / Codex CLI. Estos agentes son
de **riesgo alto** (pueden modificar código, instalar dependencias o ejecutar comandos), así
que toda acción destructiva requiere confirmación.
