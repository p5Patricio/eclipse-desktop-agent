# ADR 0001 — Eclipse como asistente desktop propio

## Estado

Aceptado — 2026-05-27, refinado tras la migración a Windows-only.

La decisión central (Eclipse como runtime propio, safety-first, modo borrador por defecto)
sigue vigente. Refinamientos posteriores: el alcance se acotó a **Windows**, los proveedores
de modelos se hicieron **intercambiables** (ollama/deepseek/openai), y OpenClaw quedó como
referencia no integrada (ver [`../OPENCLAW_STRATEGY.md`](../OPENCLAW_STRATEGY.md)).

## Contexto

Queremos un asistente de escritorio con voz, visión de pantalla, memoria y capacidad de ejecutar acciones reales. La inspiración inicial fue un asistente tipo Jarvis, pero el producto tendrá identidad propia: **Eclipse**.

También existe interés en OpenClaw porque puede aportar canales, plugins y routing multi-agente.

## Decisión

Construiremos Eclipse como runtime propio y evaluaremos OpenClaw como complemento opcional.

Decisiones concretas:

- Nombre del asistente: **Eclipse**.
- Repositorio: `eclipse-desktop-agent`.
- Visibilidad inicial: pública, siempre que no contenga secretos ni credenciales.
- MVP: voz push-to-talk, análisis de pantalla y acciones web seguras con confirmación.
- OpenClaw: evaluación en sandbox antes de integrarlo.
- Seguridad: modo borrador por defecto y confirmación para acciones sensibles.

## Consecuencias

Positivas:

- Control total de la experiencia desktop.
- Menor dependencia de una plataforma externa.
- Mejor capacidad de diseñar privacidad y seguridad desde el inicio.

Negativas:

- Más trabajo inicial.
- Hay que implementar/adaptar herramientas que OpenClaw quizá ya tenga.
- La integración con canales será más lenta si no se usa OpenClaw.

## Próximas decisiones

- Elegir proveedor de voz del MVP.
- Elegir UI inicial: CLI, tray app o dashboard web local.
- Definir si usamos Tauri/Electron en fases posteriores.
- Diseñar formato de logs y memoria.
