# Funciones de Eclipse: estado y pendientes

Resumen de qué ya funciona y qué falta para usar Eclipse como asistente diario en Windows.

## Estado

| Área | Estado | Siguiente paso |
|---|---|---|
| Plataforma | Windows-only (PAL completo) | — |
| Activación always-on | Wake word local implementado | Daemon de fondo + atajo push-to-talk |
| Voz STT/TTS | faster-whisper + SAPI funcionando | Modelo de wake word `Eclipse` propio |
| Planner multi-acción | Híbrido determinista + LLM | Mejores heurísticas para casos ambiguos |
| Proveedores LLM | ollama / deepseek / openai configurables | Verificar round-trip real de DeepSeek |
| ToolRouter | Tools nativas + MCP, con safety gates | Scheduler con paralelismo/timeout/cancelación |
| Apps de escritorio | Launcher del Menú Inicio | Enfoque/control de ventanas (UI Automation) |
| Browser automation | `agent-browser` (opcional) | Selección automática de refs semánticas |
| Notificaciones | Core SQLite + listener winrt + intents + reply | Pruebas reales con sitios autenticados |
| Visión de pantalla | Captura + análisis local + redacción | Mejorar detección de zonas sensibles |
| Agentes de codificación | Prompt contract | Launcher con confirmación y kill switch |
| Memoria local | SQLite (notificaciones, telemetría) | Permission store y audit log |
| Seguridad | Draft-first + confirmaciones + redactor | Kill switch y panel de permisos |
| Entorno | venv reproducible (`setup.bat`) | — |

## Bloques prioritarios

### Web adapters por sitio
- Parsear snapshots de `agent-browser` en `BrowserElement` (hecho) y rankear elementos
  interactivos (textbox/button/link).
- YouTube Music: abrir, buscar, elegir resultado, reproducir, verificar.
- Instagram/Messenger: abrir, preparar borrador, **no enviar** hasta confirmación.

### Control nativo
- UI Automation de Windows para leer/activar elementos accesibles.
- Verificación de resultado tras cada acción.

### Endurecimiento (Fase 5)
- Panel de permisos, audit log, kill switch, modo privado.

## Regla de seguridad

Eclipse puede preparar acciones, pero no debe enviar mensajes, publicar, borrar, instalar,
commitear, hacer push ni desplegar sin confirmación explícita.
