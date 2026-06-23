# Notificaciones y control de escritorio (Windows)

Eclipse funciona como copiloto silencioso o hablador según el contexto: captura
notificaciones de Windows, decide si interrumpir según el modo, guarda lo que llegó y
permite responder después con confirmación.

## Quick path

1. Capturar notificaciones del sistema con el listener de Windows (winrt).
2. Aplicar reglas de foco: hablar, encolar, agrupar o ignorar.
3. Guardar eventos permitidos en SQLite local.
4. Responder desde el navegador con herramientas seguras y confirmación.

## Estado actual

Implementado en `src/eclipse_agent/notifications.py` (lógica neutral) y
`src/eclipse_agent/pal/windows/notifications.py` (listener de Windows):

| Bloque | Estado |
|---|---|
| Modelo `NotificationEvent` | Hecho: evento normalizado con fuente web/nativa, urgencia, privacidad y estado. |
| Normalizador web/nativo | Hecho: Chrome/Edge/etc. se mapean a Instagram, Messenger, Gmail, YouTube, etc. |
| Reglas por app/fuente | Hecho: `NotificationRule` soporta `announce`, `queue`, `ignore` y `metadata_only`. |
| Modos normal/foco/juego/privado | Hecho: `game` y `focus` encolan; `private` guarda solo metadatos. |
| Store SQLite local | Hecho: eventos, reglas y modo actual bajo `%LOCALAPPDATA%\eclipse-agent\`. |
| Anunciador TTS | Hecho: integra `SystemTTS` (SAPI); la CLI prepara voz por defecto y habla con `--speak`. |
| Resumen de pendientes | Hecho: digest de cola y marcado como anunciado. |
| Listener de Windows | Hecho: `notifications-listen` usa `UserNotificationListener` (extra `.[notifications]`). |
| Intents de voz | Hecho: parser determinista para "modo juego", "no me avises..." y "dime qué llegó". |
| Memoria revisable/borrable | Hecho: `notifications-list` y `notifications-clear --confirmed`. |
| Respuesta en borrador | Hecho: `notifications-reply-draft` (texto/audio/grabación), abre/snapshotea la web app y rellena un ref confirmado **sin enviar**. |
| Estado post-respuesta | Hecho: `notifications-mark --status replied --confirmed`. |
| Wake/listen/respond | Hecho: `wake-command` y `wake-loop` conectan voz, intents, planner, router y TTS. |
| Smoke test | Hecho: `smoke-plan` y `smoke-simulate`. |

## Captura de notificaciones en Windows

El listener usa la API de Windows Runtime `Windows.UI.Notifications.Management`
(`UserNotificationListener`) para leer las notificaciones del sistema. Requiere el extra
opcional:

```bat
.venv\Scripts\python -m pip install -e ".[notifications]"
```

La primera vez Windows pide permiso de acceso a notificaciones; si se deniega, el listener
reporta el bloqueo en lugar de fallar.

### Límites reales

- Algunas apps ocultan contenido por configuración de privacidad.
- Instagram/Messenger en navegador aparecen como notificación de Chrome/Edge, no como
  "Instagram" puro; el normalizador intenta recuperar el origen real.
- Capturar una notificación no implica poder responder por API: para responder se usa el
  navegador con control seguro y confirmación.

## Flujo esperado: jugando un rato

```txt
1. Llega una notificación de Instagram.
2. Eclipse la captura como evento local.
3. Eclipse revisa el modo actual:
   - normal: habla.
   - juego/enfoque: guarda sin interrumpir.
   - privado: guarda solo metadatos.
4. Si puede hablar: "Tienes un mensaje de Instagram. ¿Querés responder?"
5. El usuario dicta la respuesta (STT local tras wake word).
6. Eclipse abre/prepara Instagram Web con agent-browser.
7. Eclipse escribe un borrador y pide confirmación.
8. Solo si el usuario confirma, envía.
```

## Comandos de usuario

| Comando hablado | Resultado |
|---|---|
| "Eclipse, no me avises de Instagram ni Messenger" | Silencia esas apps y guarda eventos. |
| "Eclipse, modo juego por una hora" | No habla notificaciones salvo urgentes. |
| "Eclipse, dime qué llegó" | Resume notificaciones pendientes. |
| "Eclipse, responde al grupo que ahorita entro" | Prepara borrador y pide confirmación. |
| "Eclipse, vuelve a avisarme normal" | Desactiva modo foco/silencio. |

## CLI de desarrollo

```bat
:: No molestar mientras juego una hora
eclipse-agent notifications-mode --mode game --minutes 60

:: Silenciar apps (se guardan para resumen posterior)
eclipse-agent notifications-mute --app Instagram --app Messenger

:: Simular una notificación web de Instagram emitida por Chrome
eclipse-agent notifications-ingest --app "Google Chrome" --summary "Instagram" ^
  --body "Nuevo mensaje de Ana" --source-window "Instagram - Google Chrome"

:: Leer resumen y marcarlo como anunciado
eclipse-agent notifications-summary --mark-announced

:: Listener real de notificaciones de Windows (requiere el extra .[notifications])
eclipse-agent notifications-listen --seconds 30 --execute

:: Ejecutar comandos como si vinieran de voz
eclipse-agent notifications-intent --text "Eclipse, modo juego por una hora"

:: Revisar o borrar la memoria local
eclipse-agent notifications-list --status queued
eclipse-agent notifications-clear --status announced --confirmed

:: Preparar una respuesta segura en el navegador (sin enviar)
eclipse-agent notifications-reply-draft --event-id EVENT_ID --message "Ahorita entro"
eclipse-agent notifications-mark --event-id EVENT_ID --status replied --confirmed

:: Checklist y simulación local
eclipse-agent smoke-plan
eclipse-agent smoke-simulate
```

`notifications-ingest` guarda el evento localmente. Si la decisión es anunciar, prepara el
comando TTS en dry-run; para hablar de verdad se usa `--speak`.

## Arquitectura de notificaciones

```txt
Windows Notification Listener (winrt)
  -> Notification Normalizer
  -> Privacy Filter
  -> Notification Rules Engine
  -> Local Notification Store (SQLite)
  -> Announcer / Queue
  -> Optional Reply Workflow (agent-browser + confirmación)
```

## Decisión de almacenamiento

El store operacional usa **SQLite**: el workload es transaccional (insertar notificaciones,
actualizar estados, leer una cola, borrar memoria). Viene con Python y no agrega
dependencias. La decisión está en
[`adr/0003-notification-storage-sqlite.md`](adr/0003-notification-storage-sqlite.md).

## Núcleo determinista vs cerebro opcional

La mayoría de las funciones de notificaciones **no** necesitan un LLM (capturar, silenciar,
encolar, resumir con heurísticas). El LLM solo entra para resúmenes ricos, redacción de
respuestas o razonamiento multi-paso:

```txt
Eclipse Core determinista          Eclipse Brain opcional (LLM)
  - audio local                      - resumen rico
  - notificaciones                   - redacción de respuestas
  - reglas y memoria                 - razonamiento / planificación
  - permisos y herramientas          (local Ollama o DeepSeek)
```
