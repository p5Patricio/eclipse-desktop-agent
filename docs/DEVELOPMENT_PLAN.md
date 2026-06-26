# Plan de desarrollo de Eclipse

Eclipse se construye por fases para evitar un asistente riesgoso o difícil de mantener. La
meta es un copiloto de escritorio para Windows, con voz local, eventos proactivos, visión
de pantalla y acciones seguras con confirmación.

## Resumen por fases

| Fase | Resultado | Estado |
|---|---|---|
| 0 | Repo, plan, seguridad base | ✅ |
| 1 | Daemon + wake word local + respuesta hablada | ✅ núcleo implementado |
| 2 | Visión de pantalla (opt-in, con redacción) | ✅ |
| 3 | Orquestación multi-acción + acciones web seguras | ✅ |
| 4 | Notificaciones, foco y memoria | ✅ |
| 4.5 | Bridge de agentes de codificación | ✅ prompt contract |
| — | Migración a Windows-only + provider-agnostic (DeepSeek) | ✅ |
| 5 | Copiloto diario confiable (permisos, logs, kill switch) | En progreso |

## Fase 1 — Daemon y voz

- Runtime always-on (`wake_runtime.py`) con wake word local (openwakeword).
- STT local (faster-whisper) que se activa solo tras la palabra de activación.
- TTS local (SAPI de Windows).
- Push-to-talk como fallback (pendiente: atajo global).
- CLI para probar cada pieza.

Buenas prácticas: audio temporal fuera de git; no transcribir 24/7; indicador visible de
micrófono; mostrar transcripción antes de acciones críticas.

## Fase 2 — Visión de pantalla

- Captura opt-in (`PIL.ImageGrab`).
- Redacción/blur de ventanas sensibles (bancos, gestores de contraseñas).
- Análisis con un modelo multimodal local.
- Resumen visual.

## Fase 3 — Orquestación multi-acción y acciones web

- Planner que divide instrucciones compuestas en `PlannedAction`.
- Grupos paralelos/dependientes.
- `ToolRouter` con gates de seguridad (dry-run, confirmación).
- Lanzador de apps de Windows (Menú Inicio).
- Browser automation con `agent-browser`.
- Confirmación antes de enviar/submit.

## Fase 4 — Notificaciones, foco y memoria

- Listener de notificaciones de Windows (`UserNotificationListener`, extra opcional).
- Store SQLite local (`%LOCALAPPDATA%`).
- Reglas por app: anunciar, encolar, ignorar, solo-metadatos.
- Modos normal/foco/juego/privado.
- Resúmenes, intents de voz y borradores de respuesta sin enviar.

## Fase 5 — Copiloto diario (en progreso)

Capacidades ya implementadas (voz + CLI):

- Control del sistema: volumen, medios (play/pausa/siguiente), bloqueo, batería.
- Portapapeles: leer/escribir y hablar lo copiado.
- Responder preguntas con el proveedor LLM (buscar y resumir).
- Recordatorios y timers, persistidos y disparados por el daemon.
- Memoria persistente de hechos y preferencias entre sesiones.
- Rutinas proactivas (diarias o por intervalo), disparadas por el daemon.
- Reproducir en apps web (YouTube Music) vía el adapter de navegador.
- Q&A sobre notas/PDFs (RAG): embeddings + similitud coseno en SQLite.
- Email (lectura): leer/resumir bandeja y redactar borradores por IMAP — nunca envía.

Pendiente (depende de setup externo):

- Calendario (CalDAV) para leer la agenda (requiere app password).
- Verificación real de reproducción web (requiere `agent-browser` + sesión iniciada).

Pendiente de endurecimiento:

- Panel de permisos.
- Logs revisables / audit log.
- Botón de emergencia / kill switch.
- Modo privado que desactiva captura y memoria.

## Backlog técnico

- Verificación de resultado tras cada acción de control.
- UI Automation de Windows para control fino de ventanas/widgets.
- Atajo global de push-to-talk.
- Modelo de wake word `Eclipse` propio que pase evaluación.
- Verificación real del round-trip de DeepSeek con una API key.
- Verificación real del RAG con un modelo de embeddings (Ollama `nomic-embed-text`).
- Calendario vía CalDAV (el email por IMAP ya está implementado).
- Reply-draft web para Instagram/Messenger (búsqueda y reproducción en YouTube Music ya
  implementadas; falta verificación real con `agent-browser`).
- Test harness ampliado y threat model.
