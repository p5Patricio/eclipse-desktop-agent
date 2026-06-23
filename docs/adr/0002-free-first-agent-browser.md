# ADR 0002 — Estrategia free-first y agent-browser para automatización web

## Estado

**Parcialmente superado** — 2026-05-27 (aceptado), revisado tras la migración a Windows-only.

La estrategia de automatización web (`agent-browser` como adapter, con dry-run y allowlist)
**sigue vigente**. La parte de modelos cambió: ver [`MODEL_AND_VOICE_STRATEGY.md`](../MODEL_AND_VOICE_STRATEGY.md).
Concretamente, MiniMax y los modos `free/budget/premium` quedaron reemplazados por una
abstracción **provider-agnostic** (ollama/deepseek/openai), el TTS pasó de `spd-say`/`espeak`
a SAPI de Windows, y `whisper.cpp` no se usó (se adoptó `faster-whisper`).

## Contexto

Eclipse necesita voz, razonamiento, visión y automatización de navegador. El usuario quiere evitar facturas altas y mantener el proyecto gratuito cuando sea posible. También propuso evaluar `vercel-labs/agent-browser`.

## Decisión

Adoptar una estrategia **free-first** y evaluar `agent-browser` como candidato principal de automatización web.

Decisiones concretas:

- STT inicial: local Whisper, faster-whisper o whisper.cpp.
- TTS inicial: `spd-say`/`espeak-ng`; evaluar Piper/fork mantenido después.
- LLM cloud económico: MiniMax M2.7 como primera opción si se compra plan.
- Plan MiniMax recomendado: Plus si queremos texto y Speech 2.8 en el mismo presupuesto.
- OpenAI/Claude/Gemini: adapters opcionales premium, no obligatorios.
- Browser automation: `agent-browser` como adapter experimental de Fase 3; Playwright queda como fallback.
- Computer-use cloud: solo en sandbox y nunca como flujo principal de bajo costo.

## Consecuencias

Positivas:

- El MVP puede funcionar con costo cero.
- Se reduce dependencia de APIs pagadas.
- `agent-browser` aporta refs semánticas y seguridad útil para agentes.
- MiniMax permite un modo de bajo costo si necesitamos cloud.

Negativas:

- La voz local inicial será menos natural.
- Whisper local puede requerir instalación/optimización.
- MiniMax no soporta entradas de imagen/audio en su OpenAI-compatible API de texto, así que visión y voz deben tratarse con APIs específicas o herramientas separadas.
- `agent-browser` no controla apps nativas fuera del navegador.

## Próximas tareas

- Crear `ProviderRouter`.
- Crear `CostPolicy`.
- Implementar `LocalWhisperSTT`.
- Implementar `SystemTTS` con `spd-say`/`espeak-ng`.
- Probar `agent-browser` instalado desde npm o binario publicado.
- Diseñar `AgentBrowserAdapter` con allowlist y action policy.
