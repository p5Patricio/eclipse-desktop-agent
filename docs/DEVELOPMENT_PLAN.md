# Plan de desarrollo de Eclipse

Eclipse se construirá por fases para evitar un asistente riesgoso o imposible de mantener. La primera meta es un copiloto de escritorio con voz, visión de pantalla y acciones seguras con confirmación.

## Resumen ejecutivo

| Fase | Resultado | Riesgo principal | Criterio de salida |
|---|---|---|---|
| 0 | Repo, plan, seguridad base | Alcance ambiguo | Docs y estructura inicial listas |
| 1 | Voz push-to-talk + respuesta hablada | Latencia/costos | Eclipse escucha y responde por voz |
| 2 | Visión de pantalla | Privacidad | Puede resumir pantalla con opt-in |
| 3 | Acciones web seguras | Acciones incorrectas | Puede navegar/preparar borradores con confirmación |
| 4 | Notificaciones y memoria | Datos sensibles | Captura eventos permitidos y recuerda contexto |
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
- [ ] Crear issues por fase.
- [ ] Definir stack final del MVP.

## Fase 1 — Voz mínima

**Objetivo:** hablar con Eclipse y recibir respuesta hablada.

Componentes:

- Wake mode inicial: push-to-talk.
- STT: proveedor intercambiable.
- LLM: provider adapter.
- TTS: respuesta hablada.
- CLI local para probar.

Buenas prácticas:

- Guardar audio temporal fuera de git.
- No grabar 24/7 en esta fase.
- Mostrar transcripción antes de acciones críticas.

Criterios de aceptación:

- [ ] El usuario presiona una tecla y dicta una instrucción.
- [ ] Eclipse transcribe la instrucción.
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

## Fase 3 — Acciones web seguras

**Objetivo:** controlar navegador de forma confiable.

Componentes:

- Playwright para navegador aislado.
- Perfiles de navegador separados.
- Tool executor con allowlist.
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

- [ ] Abre una URL permitida.
- [ ] Escribe en un campo controlado.
- [ ] No ejecuta submit sin confirmación.
- [ ] Captura screenshot posterior para verificar.

## Fase 4 — Notificaciones y memoria

**Objetivo:** Eclipse entiende eventos del escritorio y recuerda tareas.

Componentes:

- Listener de notificaciones del sistema.
- Memoria local con SQLite.
- Recordatorios.
- Resumen diario opt-in.

Criterios de aceptación:

- [ ] Detecta notificaciones permitidas.
- [ ] Ignora apps bloqueadas.
- [ ] Guarda solo metadatos necesarios.
- [ ] Permite borrar memoria local.

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

- Provider adapters: OpenAI, Anthropic, Gemini, local.
- Tool registry con permisos.
- Event bus interno.
- Memory store.
- Desktop bridge Linux.
- Browser automation bridge.
- Voice pipeline.
- Observability/logs.
- Test harness para tools.
- Threat model.

## Próximo paso recomendado

Crear issues de GitHub para fases 1 y 2, y empezar por un CLI local:

```bash
PYTHONPATH=src python -m eclipse_agent --help
```
