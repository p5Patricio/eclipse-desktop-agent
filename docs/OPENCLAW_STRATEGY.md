# OpenClaw: evaluación

> **Estado: fuera del scope actual.** Eclipse es un runtime propio, Windows-only y
> self-contained. OpenClaw se evaluó como infraestructura auxiliar (canales, plugins,
> routing multi-agente) pero **no está integrado** y no es una dependencia.

## Por qué Eclipse no se reemplaza por OpenClaw

La experiencia central de Eclipse (wake word local, voz local, visión de pantalla,
confirmaciones humanas, memoria local-first y proveedores intercambiables) está diseñada
alrededor de seguridad de escritorio y control total de UX/permisos. Eso justifica un
runtime propio.

## Dónde podría ayudar a futuro

Si en algún momento se evalúa una integración, los candidatos serían: canales de mensajería
(Telegram/WhatsApp/Slack/Discord), plugins/tools reutilizables, routing multi-agente o un
dashboard. Cualquier integración tendría que:

- Aislarse de forma razonable.
- No exigir credenciales personales en desarrollo.
- Permitir auditar tools/plugins.
- No romper el modelo safety-first de Eclipse.

Hasta que se cumpla y aporte valor claro, OpenClaw queda como referencia, no como parte del
producto.
