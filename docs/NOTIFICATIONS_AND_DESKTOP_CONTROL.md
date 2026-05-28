# Notificaciones y control desktop en Fedora/KDE

Eclipse debe funcionar como copiloto silencioso o hablador según el contexto. La meta es capturar notificaciones, decidir si interrumpir, guardar lo que llegó y permitir responder después con confirmación.

## Quick path

1. Capturar notificaciones del bus de sesión D-Bus.
2. Aplicar reglas de foco: hablar, silenciar, agrupar o ignorar.
3. Guardar eventos permitidos en SQLite local.
4. Responder desde navegador/apps con herramientas seguras y confirmación.

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
6. Eclipse transcribe con Whisper local.
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
| Escuchar push-to-talk con Whisper | No | Sí |
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

1. `NotificationListener` con D-Bus.
2. `NotificationStore` SQLite.
3. `NotificationRules` para silenciar apps.
4. `SystemTTS` para anunciar eventos.
5. `LocalWhisperSTT` para responder con dictado.
6. Integración `agent-browser` para preparar respuestas web.
