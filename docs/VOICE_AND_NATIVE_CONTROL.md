# Voz y control nativo Fedora/KDE

## Objetivo

Este bloque acerca a Eclipse a una prueba real de asistente: hablar por TTS local, reportar si puede escuchar/transcribir, y preparar control nativo de apps Fedora/KDE.

## Estado implementado

| Componente | Archivo | Estado |
|---|---|---|
| SystemTTS | `src/eclipse_agent/voice.py` | Prepara/ejecuta `spd-say` o `espeak-ng` |
| LocalWhisperSTT | `src/eclipse_agent/voice.py` | Transcribe archivos con `faster-whisper` cuando se ejecuta desde `venv` |
| Runtime diagnostics | `src/eclipse_agent/runtime_diagnostics.py` | Reporta binarios/módulos listos o faltantes |
| MicrophoneRecorder | `src/eclipse_agent/voice.py` | Graba WAV corto con `arecord`/`pw-record` |
| ListenOnce | `src/eclipse_agent/voice.py` | Graba una vez y transcribe una vez |
| FedoraNativeController | `src/eclipse_agent/fedora_control.py` | Abre apps `.desktop`; window focus pendiente |

## Comandos

Diagnóstico:

```bash
PYTHONPATH=src python -m eclipse_agent diagnostics
```

Hablar en dry-run:

```bash
PYTHONPATH=src python -m eclipse_agent say --text "Hola, soy Eclipse."
```

Hablar realmente:

```bash
PYTHONPATH=src python -m eclipse_agent say --text "Hola, soy Eclipse." --execute
```

Estado de escucha/STT:

```bash
PYTHONPATH=src venv/bin/python -m eclipse_agent listen-status
```

Escuchar una vez en dry-run:

```bash
PYTHONPATH=src venv/bin/python -m eclipse_agent listen --seconds 3
```

Escuchar realmente y transcribir:

```bash
PYTHONPATH=src venv/bin/python -m eclipse_agent listen --seconds 3 --execute
```

Transcribir archivo:

```bash
PYTHONPATH=src venv/bin/python -m eclipse_agent transcribe-file --audio-path /tmp/audio.wav
```

Abrir app nativa en dry-run:

```bash
PYTHONPATH=src python -m eclipse_agent fedora-open --app "YouTube Music"
```

Abrir app realmente:

```bash
PYTHONPATH=src python -m eclipse_agent fedora-open --app "YouTube Music" --execute
```

## Diagnóstico actual de la máquina

Listo:

- `spd-say`
- `espeak-ng`
- `arecord`
- `pw-record`
- `faster-whisper` en `venv`
- `dbus-monitor`
- `gdbus`
- `ydotool`

Falta:

- `pyaudio` dentro de `venv` es opcional; falló porque falta `portaudio.h`, pero no bloquea porque usamos `arecord`.
- `kdotool` opcional; no es bloqueante si usamos KWin/D-Bus/AT-SPI.

## Límites actuales

Eclipse ya puede hablar si ejecutamos `say --execute`, y puede grabar/transcribir clips con `listen --execute` usando `venv`. Todavía no tiene un loop de conversación continuo ni wake-word real.

Eclipse puede abrir apps nativas, pero todavía no puede controlar profundamente ventanas o widgets nativos. Para eso faltan:

1. Validar estrategia KWin/D-Bus para listar/enfocar ventanas.
2. Evaluar AT-SPI para elementos accesibles.
3. Usar `ydotool` solo como último recurso con permisos explícitos.
4. Agregar verificación de resultado.

## Próximos bloques

1. Implementar push-to-talk con tecla/atajo global.
2. Implementar wake-word local.
3. Conectar el texto transcrito al planner/ToolRouter.
4. Implementar daemon/wake-word.
5. Implementar D-Bus NotificationListener + SQLite store.
6. Implementar KWin/AT-SPI window focus verification.
