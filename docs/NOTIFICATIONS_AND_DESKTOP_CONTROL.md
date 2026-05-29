# Notificaciones y control desktop en Fedora/KDE

Eclipse debe funcionar como copiloto silencioso o hablador según el contexto. La meta es capturar notificaciones, decidir si interrumpir, guardar lo que llegó y permitir responder después con confirmación.

Eclipse correrá como daemon local always-on. Ese daemon puede escuchar notificaciones y wake word, pero no debe hacer transcripción continua del micrófono por defecto.

## Quick path

1. Capturar notificaciones del bus de sesión D-Bus.
2. Aplicar reglas de foco: hablar, silenciar, agrupar o ignorar.
3. Guardar eventos permitidos en SQLite local.
4. Responder desde navegador/apps con herramientas seguras y confirmación.

## Estado actual

Primer work unit implementado en `src/eclipse_agent/notifications.py`:

| Bloque | Estado |
|---|---|
| 1. Modelo `NotificationEvent` | Hecho: evento normalizado con fuente web/nativa, urgencia, privacidad y estado. |
| 2. Normalizador web/nativo | Hecho: Chrome/Firefox/etc. pueden mapearse a Instagram, Messenger, Gmail, YouTube, etc. |
| 3. Reglas por app/fuente | Hecho: `NotificationRule` soporta `announce`, `queue`, `ignore` y `metadata_only`. |
| 4. Modos normal/foco/juego/privado | Hecho: `game` y `focus` encolan; `private` guarda solo metadatos. |
| 5. SQLite local | Hecho: eventos, reglas y modo actual se guardan localmente. |
| 6. Anunciador TTS | Hecho: integra `SystemTTS`; la CLI prepara voz por defecto y habla con `--speak`. |
| 7. Resumen de pendientes + D-Bus scaffold | Hecho: digest de cola, marcado como anunciado, parser de bloques `Notify` y comando inicial `dbus-monitor`. |
| 8. Daemon D-Bus inicial | Hecho: `notifications-listen` conecta `dbus-monitor` con `NotificationCenter`. |
| 9. Intents de voz | Hecho: parser determinístico para “modo juego”, “no me avises...” y “dime qué llegó”. |
| 10. Memoria revisable/borrable | Hecho: `notifications-list` y `notifications-clear --confirmed`. |
| 11. Respuesta en borrador | Hecho: `notifications-reply-draft` acepta `--message` o `--audio-path`, abre/snapshotea web app, puede autoseleccionar un input desde snapshot JSON y rellena un ref confirmado sin enviar. |
| 12. Servicio de usuario | Hecho: `notifications-service` renderiza/instala/activa un unit systemd user para el listener. |

Falta agregar selector automático de refs para inputs de mensaje y completar
adapters nativos app por app.

## Decisión SQLite vs DuckDB

Para el store operacional de notificaciones mantenemos **SQLite**.

DuckDB es una excelente opción Python para consultas analíticas/OLAP, pero el
workload de Eclipse aquí es más transaccional: insertar notificaciones pequeñas,
actualizar estados, leer una cola y borrar memoria local. SQLite viene con
Python, no agrega dependencia y encaja mejor para esta ruta caliente del daemon.

DuckDB queda como opción complementaria futura para analytics/export de historial,
por ejemplo resúmenes semanales o consultas sobre Parquet. La decisión está en
[`docs/adr/0003-notification-storage-sqlite.md`](adr/0003-notification-storage-sqlite.md).

## Flujo esperado: jugando Rocket League

```txt
1. Llega una notificación de Instagram.
2. Eclipse la captura como evento local.
3. Eclipse revisa modo actual:
   - normal: habla.
   - juego/enfoque: guarda sin interrumpir.
   - privado: ignora o guarda solo metadatos.
4. Si puede hablar:
   Eclipse: "Tienes un mensaje de Instagram del grupo X: ... ¿quieres responder?"
5. Usuario dicta respuesta.
6. Eclipse activa STT solo después de wake word/push-to-talk y transcribe con Whisper local.
7. Eclipse abre/prepara Instagram Web con agent-browser.
8. Eclipse escribe borrador.
9. Eclipse pregunta confirmación.
10. Solo si el usuario confirma, envía.
```

## Comandos de usuario

| Comando | Resultado |
|---|---|
| “Eclipse, no me avises de Instagram ni Messenger” | Silencia esas apps y guarda eventos. |
| “Eclipse, modo juego por una hora” | No habla notificaciones salvo urgentes/allowlist. |
| “Eclipse, dime qué llegó” | Resume notificaciones pendientes. |
| “Eclipse, responde al grupo de Instagram que ahorita entro” | Prepara borrador y pide confirmación. |
| “Eclipse, vuelve a avisarme normal” | Desactiva modo foco/silencio. |

## CLI de desarrollo

```bash
# No molestar mientras juego una hora.
PYTHONPATH=src python -m eclipse_agent notifications-mode --mode game --minutes 60

# Silenciar Instagram y Messenger: se guardan para resumen posterior.
PYTHONPATH=src python -m eclipse_agent notifications-mute --app Instagram --app Messenger

# Simular una notificación web de Instagram emitida por Chrome.
PYTHONPATH=src python -m eclipse_agent notifications-ingest \
  --app "Google Chrome" \
  --summary "Instagram" \
  --body "Nuevo mensaje de Ana" \
  --source-window "Instagram - Google Chrome"

# Al terminar: leer resumen de lo que llegó y marcarlo como anunciado.
PYTHONPATH=src python -m eclipse_agent notifications-summary --mark-announced

# Ver el comando base para capturar Notify en Fedora/KDE.
PYTHONPATH=src python -m eclipse_agent notifications-dbus-command

# Preparar o ejecutar el listener D-Bus real durante 30 segundos.
PYTHONPATH=src python -m eclipse_agent notifications-listen --seconds 30
PYTHONPATH=src python -m eclipse_agent notifications-listen --seconds 30 --execute

# Renderizar o instalar el servicio systemd de usuario.
PYTHONPATH=src python -m eclipse_agent notifications-service --action render
PYTHONPATH=src python -m eclipse_agent notifications-service --action install
PYTHONPATH=src python -m eclipse_agent notifications-service --action install --execute
PYTHONPATH=src python -m eclipse_agent notifications-service --action enable-now
PYTHONPATH=src python -m eclipse_agent notifications-service --action enable-now --execute

# Ejecutar comandos como si vinieran de voz/STT.
PYTHONPATH=src python -m eclipse_agent notifications-intent \
  --text "Eclipse, modo juego por una hora"
PYTHONPATH=src python -m eclipse_agent notifications-intent \
  --text "No me avises de Instagram ni Messenger"
PYTHONPATH=src python -m eclipse_agent notifications-intent \
  --text "Dime qué llegó" \
  --mark-announced

# Revisar o borrar memoria local de notificaciones.
PYTHONPATH=src python -m eclipse_agent notifications-list --status queued
PYTHONPATH=src python -m eclipse_agent notifications-clear \
  --status announced \
  --confirmed

# Preparar una respuesta segura en navegador: primero snapshot, luego fill confirmado.
PYTHONPATH=src python -m eclipse_agent notifications-reply-draft \
  --event-id EVENT_ID \
  --message "Ahorita entro"
PYTHONPATH=src python -m eclipse_agent notifications-reply-draft \
  --event-id EVENT_ID \
  --audio-path /tmp/eclipse-reply.wav
PYTHONPATH=src python -m eclipse_agent notifications-reply-draft \
  --event-id EVENT_ID \
  --message "Ahorita entro" \
  --selector @e7 \
  --confirmed
PYTHONPATH=src python -m eclipse_agent notifications-reply-draft \
  --event-id EVENT_ID \
  --message "Ahorita entro" \
  --snapshot-json /tmp/instagram-snapshot.json \
  --auto-select \
  --confirmed
```

`notifications-ingest` guarda el evento localmente. Si la decisión es anunciar, prepara el
comando TTS en dry-run; para hablar de verdad se usa `--speak`.

## Arquitectura de notificaciones

```txt
D-Bus Notification Listener
  -> Notification Normalizer
  -> Privacy Filter
  -> Notification Rules Engine
  -> Local Notification Store
  -> Announcer / Queue
  -> Optional Reply Workflow
```

## Captura en Linux/Fedora/KDE

Fedora KDE usa notificaciones de escritorio mediante el estándar `org.freedesktop.Notifications` sobre D-Bus. Las aplicaciones envían llamadas `Notify` con campos como aplicación, resumen, cuerpo, icono, acciones, hints y expiración.

### Primera implementación

Usar un listener de sesión para observar llamadas `Notify`:

```bash
dbus-monitor "interface='org.freedesktop.Notifications',member='Notify'"
```

Después migrar a una implementación Python con `dbus-next`, `pydbus` o `jeepney`.

### Límites reales

- Algunas apps ocultan contenido por configuración de privacidad.
- Instagram/Messenger en navegador pueden aparecer como notificación de Chrome/Chromium, no como “Instagram” puro.
- En modo “No molestar” de KDE, puede cambiar qué se muestra, pero Eclipse debe tener su propia cola interna.
- Capturar notificaciones no implica poder responder por API; para responder usaremos navegador/control seguro.

## Modelo de datos mínimo

```python
NotificationEvent(
    id: str,
    received_at: datetime,
    app_name: str,
    desktop_entry: str | None,
    summary: str,
    body: str,
    urgency: str | None,
    source_window: str | None,
    status: "new" | "announced" | "queued" | "dismissed" | "replied",
    privacy_level: "full" | "metadata_only" | "redacted",
)
```

```python
NotificationRule(
    app_pattern: str,
    action: "announce" | "queue" | "ignore" | "metadata_only",
    mode: "normal" | "focus" | "game" | "private",
    expires_at: datetime | None,
)
```

## Control de apps nativas en Fedora/KDE Wayland

Eclipse debe preferir herramientas semánticas sobre clicks ciegos.

| Capa | Uso | Prioridad |
|---|---|---|
| APIs de la app / CLI | Telegram CLI, KDE tools, archivos, reproductores | Alta |
| D-Bus | Notificaciones, apps KDE, portales, MPRIS/media | Alta |
| agent-browser | Web apps como Instagram/Messenger/Gmail | Alta para web |
| AT-SPI | Leer/activar elementos accesibles de apps nativas | Media/alta |
| KWin scripting | Ventanas, foco, escritorios, estado fullscreen | Media |
| ydotool | Teclas/mouse de último recurso en Wayland | Baja, con permisos explícitos |
| OCR/screenshot | Cuando no hay accesibilidad/API | Baja, requiere privacidad |

## Wayland: implicación importante

Tu entorno actual es Fedora KDE en Wayland. Wayland es más seguro que X11 y restringe automatización global. Por eso Eclipse debe usar este orden:

1. API/CLI/D-Bus si existe.
2. Accesibilidad AT-SPI si la app la expone.
3. KWin scripting para ventanas.
4. ydotool solo como último recurso.
5. Click visual solo si no hay otra opción y con confirmación.

## ¿Necesitamos un LLM?

No para todo.

| Función | ¿Necesita LLM? | Puede ser gratis/local |
|---|---:|---:|
| Escuchar wake word local y luego Whisper | No | Sí |
| Hablar con `spd-say`/`espeak-ng` | No | Sí |
| Capturar notificaciones | No | Sí |
| Silenciar Instagram/Messenger | No | Sí |
| Leer cola de notificaciones | No | Sí |
| Dictar respuesta exacta | No necesariamente | Sí |
| Resumir muchas notificaciones | Sí o heurísticas simples | Sí, con modelo local |
| “Responde de forma amable/profesional” | Sí recomendado | Sí, con modelo local o MiniMax |
| Analizar pantalla compleja | Sí recomendado | Local multimodal futuro o cloud |
| Planear acciones multi-paso | Sí recomendado | Local/MiniMax/premium |

La arquitectura correcta es separar:

```txt
Eclipse Core determinístico
  - audio local
  - notificaciones
  - reglas
  - memoria
  - permisos
  - herramientas

Eclipse Brain opcional
  - LLM local o cloud
  - resumen
  - redacción
  - razonamiento
  - planificación
```

## Siguiente implementación recomendada

1. Marcar eventos como `replied` cuando el usuario confirme que el mensaje se envió.
2. Grabar audio directo desde el reply workflow, no solo transcribir `--audio-path`.
3. Probar selector automático con snapshots reales de Instagram/Messenger/Gmail
   y ajustar heurísticas por sitio.
4. Control nativo con D-Bus/AT-SPI cuando una app no sea web.
