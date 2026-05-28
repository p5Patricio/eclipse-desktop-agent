# Arquitectura de Eclipse

Eclipse será un asistente desktop modular. El núcleo no debe depender de un solo proveedor de modelos ni de una sola herramienta de automatización.

## Diagrama lógico

```txt
Input Layer
  - always-on daemon
  - wake word local
  - push-to-talk fallback
  - desktop notifications
  - focus/game mode
  - screen capture
        |
        v
Perception Layer
  - speech-to-text
  - screen understanding
  - notification parser
  - privacy filter
        |
        v
Agent Orchestrator
  - intent routing
  - multi-action planner
  - context assembly
  - planning
  - safety checks
  - cost policy
  - notification rules
        |
        v
Tool Executor
  - tool router
  - browser automation
  - coding-agent bridge
  - desktop automation
  - files/tools
  - OpenClaw bridge
        |
        v
Verification + Response
  - screenshot/result validation
  - TTS
  - logs
  - memory
```

## Módulos principales

| Módulo | Responsabilidad | Primera implementación |
|---|---|---|
| `activation` | Daemon, wake word, push-to-talk fallback | Always-on responsable sin STT continuo |
| `voice` | STT/TTS/realtime | `SystemTTS` + `LocalWhisperSTT` facade |
| `vision` | Capturas y análisis de pantalla | Screenshot opt-in |
| `planner` | Divide instrucciones compuestas en acciones | `ActionPlan` determinístico inicial |
| `agent` | Razonamiento y tool calling | Orchestrator simple |
| `tool_router` | Convierte `PlannedAction` en tools concretas | Dry-run + safety gates |
| `browser_automation` | Abre/busca/snapshot en navegador controlado | `AgentBrowserAdapter` dry-run |
| `desktop_apps` | Descubre/lanza apps `.desktop` | `DesktopAppLauncher` |
| `fedora_control` | Control nativo Fedora/KDE | Apertura app + KWin/AT-SPI scaffold |
| `runtime_diagnostics` | Estado de dependencias locales | CLI diagnostics |
| `tools` | Registro y ejecución de herramientas | Allowlist + confirmaciones |
| `automation` | Navegador/escritorio | `agent-browser` para web; Playwright fallback |
| `coding_agents` | Abrir Claude Code/Gemini/Codex con prompts seguros | Registry + prompt builder |
| `memory` | Recordatorios, notificaciones y contexto | SQLite local |
| `safety` | Políticas, permisos, costo, notificaciones y auditoría | Rules engine simple |
| `openclaw_bridge` | Integración opcional con OpenClaw | Adapter experimental |

## Decisiones iniciales

| Tema | Decisión |
|---|---|
| Lenguaje base | Python para MVP por velocidad e integración; TypeScript posible para UI/realtime; Rust/Go solo si hace falta daemon endurecido. |
| Automatización web | Evaluar `agent-browser` primero por snapshots de accesibilidad y refs semánticas; Playwright queda como fallback. |
| Automatización desktop | En Fedora KDE Wayland: D-Bus/API/AT-SPI/KWin primero; `ydotool` solo como último recurso. |
| Memoria | SQLite local al inicio. |
| Voz | Free-first: Whisper local para STT y TTS local simple; MiniMax/OpenAI opcionales. |
| Activación | Always-on daemon + wake-word local por defecto; push-to-talk queda como fallback; STT continuo se evita en MVP. |
| Seguridad | Confirmación obligatoria para acciones de impacto. |

## Loop de ejecución

1. Recibir evento: wake word, texto, notificación o comando.
2. Si es notificación, aplicar reglas de foco/silencio antes de hablar.
3. Construir contexto mínimo necesario.
4. Clasificar intención y dividir instrucciones compuestas en `PlannedAction`.
5. Decidir si necesita observar pantalla.
6. Proponer plan de herramientas y grupos paralelos/dependientes.
7. Rutear cada acción a una tool concreta.
8. Evaluar política de seguridad y costo.
9. Ejecutar herramienta o pedir confirmación.
10. Verificar resultado.
11. Responder por voz/texto.
12. Registrar evento y memoria permitida.

## Interfaces internas sugeridas

```python
class Tool:
    name: str
    risk_level: str
    requires_confirmation: bool

    async def run(self, input, context): ...

class SafetyPolicy:
    async def evaluate(self, plan, context): ...

class ProviderAdapter:
    async def respond(self, messages, tools=None): ...
```

## Modos de operación

| Modo | Qué permite |
|---|---|
| Observe | Solo ve/resume. No actúa. |
| Draft | Prepara texto o pasos. No confirma. |
| Copilot | Ejecuta acciones reversibles y pide confirmación en acciones sensibles. |
| Autonomous | Solo para tareas allowlist de bajo riesgo. No usar al inicio. |

## Agentes de codificación

Eclipse debe poder abrir un agente de programación externo solo bajo un flujo supervisado:

```txt
Idea dictada por el usuario
  -> Eclipse construye prompt estructurado
  -> pide confirmación de agente + proyecto + prompt
  -> abre Claude Code/Gemini/Codex en el proyecto
  -> monitorea y permite cerrar/detener
```

Primeros agentes:

| Agente | Alias de voz | Riesgo |
|---|---|---|
| Claude Code | “Claude Code”, “Cloud Code” | Alto |
| Gemini CLI | “Gemini”, “Hemini” | Alto |
| Codex CLI | “Codex” | Alto |

Razonamiento de riesgo: estos agentes pueden modificar código, instalar dependencias o ejecutar comandos. Eclipse puede preparar prompts y abrirlos, pero debe pedir confirmación para acciones destructivas, instalaciones, migraciones, commits o despliegues.

## Provider router y costo

Eclipse debe rutear modelos según costo y privacidad:

| Modo | Regla |
|---|---|
| `free` | Solo STT/TTS/modelos/herramientas locales. |
| `budget` | Permite MiniMax con cuotas/límites diarios. |
| `premium` | Permite OpenAI/Claude/Gemini solo cuando el usuario lo active. |

El MVP debe funcionar en modo `free`.

## Dependencias externas opcionales

- `agent-browser`: automatización web para agentes con refs semánticas.
- OpenClaw: gateway/canales/plugins.
- MCP servers: herramientas estandarizadas.
- Model providers: MiniMax, OpenAI, Anthropic, Gemini, local.
- Screen/memory tools: evaluar alternativas local-first.
