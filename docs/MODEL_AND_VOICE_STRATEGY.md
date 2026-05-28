# Estrategia de modelos, costo y voz

Eclipse debe ser útil sin generar una factura sorpresa. La estrategia oficial del proyecto será **free-first**: local cuando sea posible, MiniMax como opción económica, y proveedores premium solo como fallback explícito.

## Decisión rápida

| Necesidad | Opción por defecto | Alternativa económica | Fallback premium |
|---|---|---|---|
| Voz a texto | Local Whisper / faster-whisper / whisper.cpp | — | OpenAI/Gemini/otro STT cloud |
| Texto a voz | Local TTS (`spd-say`/`espeak-ng` al inicio, Piper después) | MiniMax Speech si hay plan | OpenAI/ElevenLabs |
| Cerebro LLM | MiniMax M2.7 si hay Token Plan | Modelo local vía Ollama/llama.cpp | GPT/Claude/Gemini |
| Visión de pantalla | MiniMax Image Understanding vía CLI/MCP si está disponible | Modelo local multimodal futuro | GPT/Claude/Gemini vision |
| Navegador | agent-browser local | Playwright local | Computer-use cloud solo en sandbox |

## Regla de producto

> Eclipse nunca debe depender de un proveedor pagado para funcionar en modo básico.

El modo básico debe incluir:

- Push-to-talk.
- Transcripción local.
- Respuesta de texto.
- Voz local simple.
- Automatización web local con confirmación.
- Memoria local.

## Estado detectado en la máquina

Disponible actualmente:

- `ffmpeg` y `ffplay`.
- `espeak-ng`.
- `spd-say`.
- Python `pyaudio`.
- Caché local de Hugging Face: `Systran/faster-whisper-small`.

No disponible en el Python actual:

- `whisper`.
- `faster_whisper`.
- `sounddevice`.
- `pyttsx3`.
- `webrtcvad`.
- `piper`.

Implicación: probablemente existe modelo/cache de Whisper, pero aún falta instalar el runtime Python o usar whisper.cpp.

## Voz a texto

### Opción recomendada para MVP

Usar `faster-whisper` si instalamos el paquete en un venv estable, idealmente Python 3.12 o 3.13.

Motivos:

- Corre local.
- Evita costo por audio.
- Privacidad alta.
- Ya hay un modelo `small` cacheado.
- Encaja con push-to-talk.

### Alternativa

`whisper.cpp` puede ser aún más portable y rápido como binario local. Es buena opción si queremos evitar dependencias Python pesadas.

## Texto a voz

### Fase 1: voz gratis inmediata

Usar `spd-say` o `espeak-ng` para que Eclipse hable desde el primer MVP.

Ventajas:

- Ya están instalados.
- Gratis y local.
- Baja latencia.

Desventaja:

- Voz robótica.

### Fase 2: voz local más natural

Evaluar Piper o su sucesor mantenido. Piper original está archivado, pero sigue siendo una referencia útil de TTS local. Antes de depender de él, confirmar el paquete/fork mantenido.

### Fase 3: voz premium opcional

MiniMax Speech puede ser una opción razonable si usamos plan Plus o superior. Según la documentación de MiniMax, el Token Plan Plus incluye cuota diaria de Speech 2.8, y MiniMax también ofrece suscripción de audio separada.

## MiniMax

MiniMax encaja como proveedor económico porque:

- Tiene API compatible con OpenAI SDK.
- M2.7 tiene contexto grande y capacidades agentic/coding.
- Token Plan tiene cuotas por ventana de 5 horas.
- Incluye modalidades adicionales según plan; ojo: `image-01` es generación de imagen, mientras que análisis de screenshots requiere Image Understanding vía CLI/MCP u otro endpoint específico.
- Tiene integración documentada con OpenClaw.

### Plan recomendado si queremos pagar poco

| Plan | Cuándo usarlo |
|---|---|
| Starter $10/mes | Probar M2.7 para texto/agente. No incluye Speech 2.8. |
| Plus $20/mes | Mejor candidato para Eclipse porque suma Speech 2.8 diario. |
| Pay-as-you-go | Útil para pruebas puntuales; requiere cuidado con balance. |

## Política de costo

Eclipse debe tener `CostPolicy`:

- Modo `free`: solo local, cero cloud.
- Modo `budget`: MiniMax permitido con límites diarios.
- Modo `premium`: OpenAI/Claude/Gemini permitidos por tarea explícita.

Variables sugeridas:

```env
ECLIPSE_COST_MODE=free
ECLIPSE_LLM_PROVIDER=local
ECLIPSE_STT_PROVIDER=local_whisper
ECLIPSE_TTS_PROVIDER=local_system
ECLIPSE_MAX_CLOUD_CALLS_PER_DAY=0
```

Con MiniMax:

```env
ECLIPSE_COST_MODE=budget
ECLIPSE_LLM_PROVIDER=minimax
ECLIPSE_TTS_PROVIDER=minimax_or_local
MINIMAX_API_KEY=
MINIMAX_BASE_URL=https://api.minimax.io/v1
ECLIPSE_MAX_CLOUD_CALLS_PER_DAY=200
```

## Cambios al plan

1. Fase 1 debe implementarse sin cloud obligatorio.
2. Agregar `ProviderRouter` y `CostPolicy` antes de integrar proveedores pagados.
3. Priorizar Whisper local para STT.
4. Usar `spd-say`/`espeak-ng` para voz inicial.
5. Evaluar MiniMax Plus como plan recomendado si queremos voz más natural y un LLM económico.
6. Mantener OpenAI/Claude/Gemini como adapters opcionales, no como dependencia del MVP.
