# Voz y control nativo (Windows)

## Objetivo

Que Eclipse hable por TTS local, reporte si puede escuchar/transcribir, y prepare/ejecute
control nativo de Windows (apps, ventanas, capturas, tipeo) con confirmación.

## Estado implementado

| Componente | Archivo | Estado |
|---|---|---|
| `SystemTTS` | `src/eclipse_agent/voice.py` | Sintetiza voz con SAPI de Windows (`pal/windows/voice.py`) |
| `LocalWhisperSTT` | `src/eclipse_agent/voice.py` | Transcribe con `faster-whisper` |
| `MicrophoneRecorder` | `src/eclipse_agent/voice.py` | Graba WAV corto con `sounddevice` + VAD (corte por silencio) |
| `ListenOnce` | `src/eclipse_agent/voice.py` | Graba una vez y transcribe una vez |
| `OpenWakeWordTrigger` | `src/eclipse_agent/voice.py` | Detección de wake word con openwakeword |
| `WakeRuntime` | `src/eclipse_agent/wake_runtime.py` | Loop wake → escuchar → razonar → responder |
| `runtime_diagnostics` | `src/eclipse_agent/runtime_diagnostics.py` | Reporta módulos/binarios listos o faltantes |

El control nativo de Windows vive en la **Platform Abstraction Layer** (`pal/windows/`):

| Capacidad | Implementación |
|---|---|
| Lanzar apps | `WindowsAppLauncher` busca accesos directos `.lnk` del Menú Inicio y abre con `os.startfile` |
| Listar/enfocar ventanas | `WindowsWindowManager` vía `win32gui` |
| Captura de pantalla | `WindowsScreenCapture` vía `PIL.ImageGrab` |
| Tipeo nativo | `WindowsInputSynthesizer` (requiere `--confirmed`) |

## Comandos

```bat
:: Diagnóstico de capacidades
eclipse-agent diagnostics

:: Hablar (dry-run, luego real)
eclipse-agent say --text "Hola, soy Eclipse."
eclipse-agent say --text "Hola, soy Eclipse." --execute

:: Estado de STT y escucha real
eclipse-agent listen-status
eclipse-agent listen --seconds 3 --execute
eclipse-agent transcribe-file --audio-path C:\ruta\audio.wav

:: Control de escritorio
eclipse-agent open-app --app "Notepad" --execute
eclipse-agent list-windows
eclipse-agent screenshot --output captura.png --execute
eclipse-agent type-text --text "hola" --confirmed --execute
```

## Límites actuales

Eclipse ya habla (SAPI), graba y transcribe (faster-whisper), detecta wake word
(openwakeword), abre apps, lista ventanas, captura pantalla y tipea texto. Lo que falta
para control profundo de UI:

1. Enfoque/manipulación fina de ventanas y widgets (UI Automation de Windows).
2. Verificación de resultado tras cada acción.
3. Un modelo de wake word `Eclipse` propio que pase evaluación (hoy usa `hey_jarvis`).

## Próximos bloques

1. Push-to-talk con atajo global.
2. Integrar UI Automation (`uiautomation`) para leer/activar elementos accesibles.
3. Verificación de resultado en acciones de control.
