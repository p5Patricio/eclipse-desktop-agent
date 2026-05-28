# Funciones pendientes de Eclipse

Este documento resume qué ya existe como scaffold y qué falta para que Eclipse se use como asistente diario.

## Estado rápido

| Área | Estado | Siguiente paso |
|---|---|---|
| Activación always-on | Scaffold | Daemon real + wake word local |
| Voz STT/TTS | TTS + STT one-shot probado | Push-to-talk y wake-word |
| Planner multi-acción | Scaffold probado | Planner con LLM/local heuristics para casos ambiguos |
| ToolRouter | Scaffold probado | Scheduler con paralelismo, timeout y cancelación |
| Desktop apps | Apertura scaffold probado | Enfocar ventanas KDE y verificar |
| Browser automation | Navegador real probado | Selector automático de refs semánticas |
| Browser interaction loop | Snapshot JSON parseado | Elegir refs semánticas automáticamente |
| YouTube Music | Launcher detectado | Buscar canción y reproducir resultado correcto |
| Instagram/Messenger | URLs preparadas | Preparar respuestas sin enviar, con confirmación |
| Notificaciones | Diseñado | D-Bus listener + SQLite store + reglas |
| Agentes de codificación | Prompt contract | Launcher de Claude/Gemini/Codex con confirmación |
| Memoria local | Diseñada | SQLite para eventos, permisos y auditoría |
| Seguridad | Primitivas | Permission store, audit log y kill switch |

## Bloques prioritarios

### 1. Probar `agent-browser` real

- Instalado `agent-browser` global.
- Ejecutado `agent-browser install` y descargado Chrome for Testing.
- Probado `example.com` con snapshot real.
- Confirmado formato JSON de `batch --json`.

### 2. Snapshot parser

- Convertir salida JSON en objetos `BrowserElement`: hecho.
- Detectar refs `e1`/`@e1`: hecho.
- Falta filtrar/rankear elementos interactivos: textbox, button, link, menuitem.
- Falta mantener URL/título/snapshot timestamp en memoria local.

### 3. Action selector

- Para instrucciones simples, elegir refs con heurísticas:
  - campo search/email/message por label/role/text.
  - botón play/send/search por role/name.
- Para instrucciones ambiguas, preguntar al usuario.
- Más adelante, usar LLM local/MiniMax para decidir refs.

### 4. YouTube Music adapter

- Abrir app/PWA.
- Snapshot.
- Encontrar campo de búsqueda.
- Fill con canción/artista.
- Press Enter.
- Snapshot resultados.
- Click resultado más probable.
- Verificar reproducción.

### 5. Messenger/Instagram draft adapter

- Abrir página.
- Snapshot.
- Buscar contacto/conversación.
- Preparar texto en input.
- No enviar hasta confirmación explícita.
- Después de confirmar, click/press send y verificar.

### 6. Voz y control nativo

- Probar `say --execute` con `spd-say`.
- STT one-shot ya probado; falta push-to-talk/wake-word.
- Validar KWin/D-Bus/AT-SPI para enfocar ventanas.

### 7. Daemon + voz

- Proceso background.
- Wake word local.
- STT tras wake word.
- TTS de respuesta.
- Indicador de micrófono y kill switch.

## Regla de seguridad

Eclipse puede preparar acciones, pero no debe enviar mensajes, publicar, borrar, instalar, commitear, hacer push o desplegar sin confirmación explícita.
