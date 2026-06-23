# Estrategia de modelos y voz

Eclipse debe ser útil sin generar una factura sorpresa, y sin obligar a nadie a tener una
GPU. La estrategia es **provider-agnostic con default local**: la voz corre siempre local;
el razonamiento usa el proveedor que el usuario elija.

## Activación

Eclipse usa **wake word local responsable**: un detector liviano (openwakeword) escucha en
reposo y solo activa Whisper cuando oye la palabra de activación. Así da la sensación
Alexa/Jarvis sin transcribir audio 24/7.

| Modo | RAM idle | Privacidad | Recomendación |
|---|---:|---|---|
| Wake word local | bajo | alta (todo local) | **Default** |
| Push-to-talk | mínimo | máxima | Fallback de batería/privacidad |
| STT continuo | alto | riesgo | Evitar |

## Voz (siempre local)

| Función | Implementación |
|---|---|
| Speech-to-text | `faster-whisper` (modelo `small` por defecto) |
| Text-to-speech | SAPI de Windows |
| Wake word | openwakeword (`hey_jarvis` por defecto; modelo `Eclipse` propio entrenable) |

La voz no depende de ningún proveedor pagado: STT y TTS son locales.

## Razonamiento (proveedor configurable)

El planificador es híbrido: reglas deterministas rápidas + capa LLM para instrucciones
complejas. La capa LLM es provider-agnostic porque DeepSeek, Ollama y OpenAI hablan la
misma API OpenAI-compatible.

| Proveedor | Cuándo usarlo |
|---|---|
| `ollama` (default) | Privacidad total y offline; requiere correr Ollama localmente. |
| `deepseek` | Económico y sin GPU; requiere `DEEPSEEK_API_KEY`. La mejor opción para que cualquiera lo corra. |
| `openai` | Si ya tenés cuenta de OpenAI; requiere `OPENAI_API_KEY`. |

Se elige con `--provider` o `ECLIPSE_LLM_PROVIDER` en `.env`.

## Visión de pantalla

El análisis de pantalla se mantiene **local** (modelo multimodal `qwen2.5vl` vía Ollama),
porque DeepSeek no expone visión. Si se usa DeepSeek para el texto, la visión sigue
corriendo local de forma independiente.

## Regla de producto

> El modo básico (wake word, STT, TTS, notificaciones, memoria) debe funcionar sin ningún
> proveedor pagado. Los proveedores en la nube son una opción, no un requisito.
