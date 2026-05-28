# Eclipse Desktop Agent

Eclipse es un asistente personal de escritorio, controlado por voz, capaz de observar la pantalla, entender contexto, preparar acciones, pedir confirmación y ejecutar tareas reales con seguridad.

> Objetivo: cuando digas **"Eclipse"**, el asistente debe estar listo para escuchar instrucciones, analizar lo que ocurre en tu computadora y actuar como copiloto confiable.

## Quick path

1. Leer [`docs/DEVELOPMENT_PLAN.md`](docs/DEVELOPMENT_PLAN.md) para entender el plan por fases.
2. Revisar [`docs/MODEL_AND_VOICE_STRATEGY.md`](docs/MODEL_AND_VOICE_STRATEGY.md) para mantener Eclipse free-first.
3. Revisar [`docs/SECURITY.md`](docs/SECURITY.md) antes de implementar automatización real.
4. Usar [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) como guía técnica.
5. Revisar [`docs/NOTIFICATIONS_AND_DESKTOP_CONTROL.md`](docs/NOTIFICATIONS_AND_DESKTOP_CONTROL.md) para el flujo de notificaciones y apps nativas en Fedora/KDE.
6. Evaluar [`docs/AGENT_BROWSER_EVALUATION.md`](docs/AGENT_BROWSER_EVALUATION.md) para automatización web.
7. Evaluar OpenClaw con [`docs/OPENCLAW_STRATEGY.md`](docs/OPENCLAW_STRATEGY.md), sin convertirlo todavía en dependencia crítica.

## Principios del proyecto

| Principio | Decisión |
|---|---|
| Local-first | Eclipse debe correr principalmente en la computadora del usuario. |
| Safety-first | Acciones sensibles requieren confirmación humana. |
| Draft-first | Al inicio Eclipse prepara borradores; no envía ni modifica sin permiso. |
| Provider-agnostic | OpenAI, Claude, Gemini y modelos locales deben poder intercambiarse. |
| Auditabilidad | Toda acción importante debe quedar registrada. |
| Plugins controlados | Las capacidades se agregan por herramientas con permisos explícitos. |

## Alcance inicial

El MVP no busca autonomía total. Busca demostrar este flujo:

```txt
Wake word / push-to-talk
  -> transcripción
  -> análisis de pantalla
  -> razonamiento del agente
  -> acción segura o borrador
  -> confirmación humana
  -> respuesta hablada
  -> memoria/log
```

## Estructura inicial

```txt
src/eclipse_agent/          Núcleo Python inicial
  main.py                   CLI placeholder para validar el paquete
  config.py                 Configuración base
  safety.py                 Modelo inicial de política de seguridad
docs/                       Plan, arquitectura, seguridad y OpenClaw
  adr/                      Decisiones arquitectónicas
```

## Estado

Proyecto en fase **0: diseño e inicialización**.

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
