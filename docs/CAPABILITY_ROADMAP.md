# Funciones de Eclipse: estado y pendientes

Resumen de qué ya funciona y qué falta para usar Eclipse como asistente diario en Windows.

## Capacidades del asistente

Además de abrir apps/webs y manejar notificaciones, Eclipse ya *hace cosas* por voz y CLI:

| Capacidad | Estado | Comandos |
|---|---|---|
| Control del sistema (volumen, medios, bloqueo, batería) | ✅ | `system` |
| Portapapeles (leer/escribir, hablar lo copiado) | ✅ | `clipboard` |
| Responder preguntas (resumen vía LLM) | ✅ | `ask` |
| Recordatorios y timers (disparados por el daemon) | ✅ | `remind`, `reminders-list`, `reminders-check` |
| Memoria persistente de hechos/preferencias | ✅ | `remember`, `memory-list`, `memory-recall`, `memory-forget` |
| Rutinas proactivas (diarias o por intervalo) | ✅ | `routine-add`, `routines-list`, `routine-remove`, `routines-check` |
| Reproducir en apps web (abre la búsqueda en tu navegador) | ✅ | `play-media` |
| Q&A sobre notas/PDFs (RAG) | ✅ pipeline; requiere modelo de embeddings (Ollama) | `docs-add`, `docs-list`, `docs-ask`, `docs-clear` |
| Email: leer/resumir bandeja + borradores (IMAP, read-only) | ✅ pipeline; requiere app password | `email-list`, `email-summary`, `email-draft` |
| Agenda del calendario (iCal, read-only, recurrencias) | ✅ pipeline; requiere URL secreta iCal | `agenda` |

## Estado de la plataforma

| Área | Estado | Siguiente paso |
|---|---|---|
| Plataforma | Windows-only (PAL completo) | — |
| Activación always-on | Wake word local + daemon con pollers de recordatorios y rutinas | Atajo push-to-talk global |
| Voz STT/TTS | faster-whisper + voces WinRT (neural) con fallback SAPI | Modelo de wake word `Eclipse` propio |
| Planner multi-acción | Híbrido determinista + LLM | Mejores heurísticas para casos ambiguos |
| Proveedores LLM | ollama / deepseek / openai configurables | Verificar round-trip real de DeepSeek |
| ToolRouter | Tools nativas + MCP, con safety gates | Scheduler con paralelismo/timeout/cancelación |
| Apps de escritorio | Launcher del Menú Inicio | Enfoque/control de ventanas (UI Automation) |
| Browser automation | Adapter + selección de refs + orquestación search-and-play | Verificación real con `agent-browser` y sesión iniciada |
| Notificaciones | Core SQLite + listener winrt + intents + reply | Pruebas reales con sitios autenticados |
| Visión de pantalla | Captura + análisis local + redacción | Mejorar detección de zonas sensibles |
| Agentes de codificación | Prompt contract | Launcher con confirmación y kill switch |
| Memoria local | SQLite: notificaciones, telemetría, recordatorios, hechos, rutinas, documentos | Permission store y audit log |
| Q&A de documentos (RAG) | Pipeline embeddings + coseno en SQLite (sin base vectorial) | Verificar con un modelo de embeddings real (Ollama) |
| Seguridad | Draft-first + confirmaciones + redactor + kill switch + audit log | Panel de permisos |
| Entorno | venv reproducible (`setup.bat`) + CI en Windows | — |

## Pendiente

### Control nativo

- UI Automation de Windows para leer/activar elementos accesibles.
- Verificación de resultado tras cada acción.

### Endurecimiento

- Panel de permisos y modo privado. (Audit log y kill switch ya implementados.)
- Atajo global de push-to-talk. (Voz neural, app de bandeja y kill switch ya implementados.)

## Regla de seguridad

Eclipse puede preparar acciones, pero no debe enviar mensajes, publicar, borrar, instalar,
commitear, hacer push ni desplegar sin confirmación explícita.
