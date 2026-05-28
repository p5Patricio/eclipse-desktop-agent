# Arquitectura de Eclipse

Eclipse será un asistente desktop modular. El núcleo no debe depender de un solo proveedor de modelos ni de una sola herramienta de automatización.

## Diagrama lógico

```txt
Input Layer
  - push-to-talk
  - wake word futuro
  - desktop notifications
  - screen capture
        |
        v
Perception Layer
  - speech-to-text
  - screen understanding
  - notification parser
        |
        v
Agent Orchestrator
  - intent routing
  - context assembly
  - planning
  - safety checks
        |
        v
Tool Executor
  - browser automation
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
| `voice` | STT/TTS/realtime | Provider adapter + push-to-talk |
| `vision` | Capturas y análisis de pantalla | Screenshot opt-in |
| `agent` | Razonamiento y tool calling | Orchestrator simple |
| `tools` | Registro y ejecución de herramientas | Allowlist + confirmaciones |
| `automation` | Navegador/escritorio | `agent-browser` para web; Playwright fallback |
| `memory` | Recordatorios y contexto | SQLite local |
| `safety` | Políticas, permisos y auditoría | Rules engine simple |
| `openclaw_bridge` | Integración opcional con OpenClaw | Adapter experimental |

## Decisiones iniciales

| Tema | Decisión |
|---|---|
| Lenguaje base | Python para MVP por velocidad e integración; TypeScript posible para UI/realtime; Rust/Go solo si hace falta daemon endurecido. |
| Automatización web | Evaluar `agent-browser` primero por snapshots de accesibilidad y refs semánticas; Playwright queda como fallback. |
| Automatización desktop | PyAutoGUI/AT-SPI/xdotool según entorno, detrás de una interfaz. |
| Memoria | SQLite local al inicio. |
| Voz | Free-first: Whisper local para STT y TTS local simple; MiniMax/OpenAI opcionales. |
| Seguridad | Confirmación obligatoria para acciones de impacto. |

## Loop de ejecución

1. Recibir evento: voz, texto, notificación o comando.
2. Construir contexto mínimo necesario.
3. Clasificar intención.
4. Decidir si necesita observar pantalla.
5. Proponer plan de herramientas.
6. Evaluar política de seguridad.
7. Ejecutar herramienta o pedir confirmación.
8. Verificar resultado.
9. Responder por voz/texto.
10. Registrar evento y memoria permitida.

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
