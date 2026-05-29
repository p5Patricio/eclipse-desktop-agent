# Plan de desarrollo de Eclipse

Eclipse se construirá por fases para evitar un asistente riesgoso o imposible de mantener. La primera meta es un copiloto de escritorio siempre disponible, con voz, eventos proactivos, visión de pantalla y acciones seguras con confirmación.

## Resumen ejecutivo

| Fase | Resultado | Riesgo principal | Criterio de salida |
|---|---|---|---|
| 0 | Repo, plan, seguridad base | Alcance ambiguo | Docs y estructura inicial listas |
| 1 | Daemon always-on + wake word local + respuesta hablada | Latencia/calidad de voz/privacidad | Eclipse permanece activo, despierta con “Eclipse” y responde por voz sin cloud obligatorio |
| 2 | Visión de pantalla | Privacidad | Puede resumir pantalla con opt-in |
| 3 | Orquestación multi-acción + acciones web seguras | Acciones incorrectas | Puede dividir instrucciones, abrir apps/navegador y preparar borradores con confirmación |
| 4 | Notificaciones, foco y memoria | Datos sensibles/interrupciones | Captura, silencia, agrupa y resume eventos permitidos |
| 5 | Integración OpenClaw | Superficie de ataque | OpenClaw probado en sandbox y conectado por bridge |
| 6 | Modo copiloto diario | Confiabilidad | Uso cotidiano con logs, permisos y rollback |

## Fase 0 — Fundación del proyecto

**Objetivo:** dejar una base clara antes de escribir automatización peligrosa.

Entregables:

- Repositorio público sin secretos.
- README orientado a producto.
- Plan de desarrollo.
- Arquitectura inicial.
- Política de seguridad.
- Estrategia para OpenClaw.
- Primer ADR con decisiones base.

Checklist:

- [x] Nombre del asistente definido: **Eclipse**.
- [x] Estrategia híbrida: runtime propio + OpenClaw como alternativa/complemento.
- [x] Definir estrategia free-first del MVP.
- [ ] Crear issues por fase.

## Fase 1 — Daemon always-on y voz mínima

**Objetivo:** que Eclipse esté activo en segundo plano, pueda reaccionar a eventos permitidos y despierte al oír “Eclipse” sin transcribir todo el audio 24/7.

Componentes:

- Runtime always-on como daemon local.
- Wake mode inicial recomendado: detector local de palabra clave “Eclipse”.
- Push-to-talk como fallback de privacidad/batería.
- Evitar `continuous_stt` por defecto.
- STT: Whisper local, faster-whisper o whisper.cpp.
- LLM: provider adapter con modo `free`, `budget` y `premium`.
- TTS: `spd-say`/`espeak-ng` primero; Piper/MiniMax después.
- CLI local para probar.

Buenas prácticas:

- Guardar audio temporal fuera de git.
- No transcribir 24/7 en esta fase.
- Mostrar indicador visible cuando el micrófono esté escuchando después del wake word.
- Mostrar transcripción antes de acciones críticas.

Criterios de aceptación:

- [ ] El daemon inicia y muestra estado de activación.
- [ ] El usuario dice “Eclipse” o usa push-to-talk fallback.
- [ ] Eclipse transcribe la instrucción con motor local.
- [ ] Eclipse responde en voz alta.
- [ ] La sesión queda logueada sin datos sensibles innecesarios.

## Fase 2 — Visión de pantalla

**Objetivo:** Eclipse puede responder “qué hay en pantalla”.

Componentes:

- Screenshot opt-in.
- Redacción/blur de zonas sensibles cuando sea posible.
- Envío de imagen a modelo multimodal.
- Resumen visual y entidades detectadas.

Criterios de aceptación:

- [ ] Comando: “Eclipse, ¿qué ves?”
- [ ] Captura una screenshot.
- [ ] Resume la pantalla.
- [ ] Pide permiso antes de guardar screenshot.

## Fase 3 — Orquestación multi-acción y acciones web seguras

**Objetivo:** controlar navegador y apps de forma confiable, incluso cuando una sola instrucción contiene varias tareas.

Componentes:

- Planner multi-acción para dividir instrucciones por intención.
- Grupos paralelos/dependientes para ejecutar acciones independientes a la vez.
- Tool router para convertir `PlannedAction` en herramientas concretas.
- Desktop app launcher para apps instaladas como YouTube Music.
- Browser automation adapter con `agent-browser` para navegador aislado.
- Snapshots con refs semánticas como siguiente iteración.
- Playwright como fallback para scripts deterministas.
- Perfiles de navegador separados.
- Tool executor con allowlist, `--allowed-domains` y action policy.
- Confirmación antes de submit/enviar.

Ejemplo de flujo:

```txt
Usuario: Eclipse, responde este mensaje con “voy en camino”.
Eclipse: Detecto Instagram abierto. Prepararé el borrador, pero no lo enviaré sin confirmar.
Eclipse: Escribe el borrador.
Eclipse: ¿Confirmas enviar?
Usuario: Sí.
Eclipse: Envía y registra acción.
```

Criterios de aceptación:

- [ ] “Reproduce X en YouTube Music y abre Instagram/Messenger” se divide en varias acciones.
- [ ] `ToolRouter` prepara/ejecuta acciones low-risk en dry-run/execute.
- [ ] `DesktopAppLauncher` descubre `.desktop` y lanza YouTube Music.
- [ ] `AgentBrowserAdapter` prepara comandos `open/search/snapshot` con allowlist de dominio.
- [ ] Acciones independientes se pueden ejecutar en paralelo con timeouts/cancelación.
- [ ] Abre una URL permitida.
- [ ] Escribe en un campo controlado.
- [ ] No ejecuta submit sin confirmación.
- [ ] Captura screenshot posterior para verificar.

## Fase 4 — Notificaciones, foco y memoria

**Objetivo:** Eclipse entiende eventos del escritorio sin interrumpir cuando el usuario está ocupado.

Componentes:

- Listener de notificaciones D-Bus (`org.freedesktop.Notifications`).
- Memoria local con SQLite.
- Reglas por app: anunciar, silenciar, agrupar, ignorar.
- Modo foco/juego/privado.
- Resumen de notificaciones pendientes.
- Recordatorios.
- Resumen diario opt-in.

Criterios de aceptación:

- [x] Detecta notificaciones permitidas desde bloques `Notify` de D-Bus.
- [x] “No me avises de Instagram ni Messenger” silencia esas apps en reglas persistidas.
- [x] “Modo juego” guarda eventos sin hablar.
- [x] “Dime qué llegó” resume la cola de notificaciones.
- [x] Ignora apps bloqueadas mediante reglas `ignore`.
- [x] Guarda solo metadatos necesarios cuando esté en modo privado.
- [x] Permite borrar memoria local con confirmación.

Estado del primer work unit:

- `NotificationStore` SQLite guarda eventos, reglas y modo actual.
- `NotificationCenter` decide si anuncia o encola.
- `notifications-mode`, `notifications-mute`, `notifications-ingest`,
  `notifications-summary` y `notifications-dbus-command` permiten validar el flujo.
- `notifications-listen` ejecuta el primer listener D-Bus con `dbus-monitor`.
- `notifications-service` renderiza/instala/activa el servicio systemd de usuario.
- `notifications-intent` cubre frases como “modo juego”, “no me avises...”
  y “dime qué llegó”.
- `notifications-reply-draft` prepara respuestas web en borrador sin enviar y puede
  usar `--message` o transcribir `--audio-path`.
- Falta automatizar selección de refs y completar adapters nativos app por app.

## Fase 4.5 — Bridge de agentes de codificación

**Objetivo:** permitir que Eclipse abra agentes como Claude Code, Gemini CLI o Codex CLI en un proyecto y les entregue un prompt estructurado a partir de una idea dictada por el usuario.

Componentes:

- Registro de agentes soportados y aliases de voz: “Claude Code”, “Cloud Code”, “Gemini/Hemini”, “Codex”.
- Prompt builder con contexto de proyecto, idea, restricciones y reglas de seguridad.
- Apertura controlada de terminal/proceso en el directorio del proyecto.
- Confirmación antes de instalar dependencias, migrar, borrar archivos, commitear o ejecutar comandos destructivos.
- Kill switch para detener procesos de agentes.

Ejemplo de flujo:

```txt
Usuario: Eclipse, abre Claude Code en mi proyecto de portafolio y desarrolla una landing.
Eclipse: Preparé un prompt para Claude Code. ¿Confirmas abrirlo en /ruta/proyecto?
Usuario: Sí.
Eclipse: Abre Claude Code, pega/envía el prompt y monitorea el proceso.
```

Criterios de aceptación:

- [ ] Resuelve alias de voz al agente correcto.
- [ ] Genera prompt seguro y estructurado.
- [ ] Abre el agente en el proyecto confirmado.
- [ ] Registra qué prompt entregó.
- [ ] Requiere confirmación para acciones de alto impacto.

## Fase 5 — OpenClaw como complemento

**Objetivo:** evaluar si OpenClaw acelera canales, plugins o multi-agent routing.

Regla:

> OpenClaw no será dependencia crítica hasta probarlo en sandbox.

Evaluación:

- Canales: Telegram, WhatsApp, Discord, Slack.
- Plugins/tools.
- Voice/talk mode.
- Políticas/sandboxing.
- Bridge con Eclipse.

Criterios de aceptación:

- [ ] OpenClaw corre en VM/usuario separado/contenedor.
- [ ] No usa credenciales personales reales en pruebas iniciales.
- [ ] Se documentan riesgos y beneficios.
- [ ] Se decide si queda como bridge, plugin o referencia.

## Fase 6 — Copiloto diario

**Objetivo:** usar Eclipse en tareas normales con seguridad.

Capacidades candidatas:

- Responder mensajes con confirmación.
- Tomar notas de pantalla.
- Recordatorios contextuales.
- Abrir apps y preparar workflows.
- Buscar información y resumir.
- Ejecutar scripts permitidos.

Criterios de aceptación:

- [ ] Panel de permisos.
- [ ] Logs revisables.
- [ ] Botón de emergencia / kill switch.
- [ ] Modo privado que desactiva captura y memoria.

## Backlog técnico

- Provider router con `CostPolicy`.
- Provider adapters: local, MiniMax, OpenAI, Anthropic, Gemini.
- Tool registry con permisos.
- Event bus interno.
- Memory store.
- Desktop bridge Linux/Fedora KDE con D-Bus, AT-SPI, KWin y `ydotool` como último recurso.
- Notification listener + notification rules engine.
- Browser automation bridge con `agent-browser`.
- Coding agent bridge para Claude Code/Gemini/Codex.
- Voice pipeline.
- Observability/logs.
- Test harness para tools.
- Threat model.

## Próximo paso recomendado

Implementar el work unit de Fase 1:

```bash
PYTHONPATH=src python -m eclipse_agent status
PYTHONPATH=src python -m eclipse_agent resource-plan
```
