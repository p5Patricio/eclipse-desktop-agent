# Eclipse Desktop Agent

> Asistente de voz para Windows, estilo Jarvis — la voz corre local, el cerebro es
> intercambiable (DeepSeek o modelo local), y cada acción sensible pide confirmación.

![CI](https://github.com/p5Patricio/eclipse-desktop-agent/actions/workflows/ci.yml/badge.svg)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6)
![Python](https://img.shields.io/badge/python-3.11%2B-3776AB)
![License](https://img.shields.io/badge/license-MIT-green)

Eclipse es un **asistente personal de escritorio para Windows**, estilo Jarvis: vive en
segundo plano, despierta con una palabra de activación, entiende lo que le pedís, prepara
acciones, te pide confirmación cuando hace falta y las ejecuta de forma segura — además de
hablarte de vuelta.

> Solo Windows. Toda la voz (wake word + transcripción + síntesis) corre **localmente** en
> tu máquina. El razonamiento puede usar un modelo **local** (Ollama) o un proveedor en la
> nube **barato** (DeepSeek), según prefieras privacidad o simplicidad.

## Principios

| Principio | Qué significa |
|---|---|
| **Voz local** | Wake word (openwakeword), transcripción (faster-whisper) y síntesis (SAPI de Windows) corren en tu máquina. |
| **Provider-agnostic** | El planificador funciona con Ollama (local), DeepSeek o OpenAI cambiando un valor de config. |
| **Safety-first** | Las acciones sensibles requieren confirmación humana explícita. |
| **Draft-first** | Por defecto Eclipse prepara borradores; no envía ni modifica sin permiso. |
| **Auditable** | Las notificaciones y acciones quedan registradas localmente en SQLite. |
| **Privacidad de pantalla** | Las capturas se analizan con un modelo de visión local y se redactan ventanas sensibles (bancos, gestores de contraseñas) antes de procesarlas. |

## Requisitos

- **Windows 10/11**
- **Python 3.11+** (probado en 3.14)
- Opcional: [Ollama](https://ollama.com/) si querés el modelo local; una API key de
  [DeepSeek](https://platform.deepseek.com/) si preferís la nube.

## Instalación

Setup en un comando (crea el entorno virtual e instala todo):

```bat
scripts\setup.bat
```

O manualmente:

```bat
py -m venv .venv
.venv\Scripts\python -m pip install -e ".[voice,dev]"
```

Extras opcionales:

```bat
:: Escucha real de notificaciones de Windows
.venv\Scripts\python -m pip install -e ".[notifications]"

:: Automatización web (CLI externa de Node)
npm install -g agent-browser
```

Verificá qué capacidades están disponibles:

```bat
.venv\Scripts\eclipse-agent diagnostics
```

## Configuración

Eclipse carga automáticamente un archivo `.env` de la raíz del proyecto al arrancar.
Creá uno con tu configuración de proveedor:

```ini
# Proveedor del planificador: ollama (local, por defecto), deepseek o openai
ECLIPSE_LLM_PROVIDER=ollama

# Requerido si usás DeepSeek
DEEPSEEK_API_KEY=

# Requerido si usás OpenAI
OPENAI_API_KEY=

# Overrides avanzados (opcionales) sobre el preset del proveedor
# ECLIPSE_LLM_BASE_URL=
# ECLIPSE_LLM_MODEL=

# Visión de pantalla (se mantiene local: DeepSeek no tiene modelo multimodal)
# ECLIPSE_VISION_MODEL=qwen2.5vl:7b

# Voz y wake word
# ECLIPSE_WHISPER_MODEL=small
# ECLIPSE_WAKE_THRESHOLD=0.5
# ECLIPSE_BUILTIN_WAKEWORD=hey_jarvis
```

También podés elegir el proveedor por línea de comandos en cada invocación con
`--provider {ollama,deepseek,openai}`.

> **Visión:** el análisis de pantalla usa un modelo multimodal local (`qwen2.5vl` vía
> Ollama). DeepSeek no expone visión, así que esa función permanece local aunque uses
> DeepSeek para el texto.

## Uso

Arrancá el daemon de wake word (palabra de activación `hey_jarvis` por defecto hasta que
entrenes un modelo `Eclipse` propio):

```bat
scripts\start_eclipse.bat
```

O usá la CLI directamente (con el venv activo, o vía `.venv\Scripts\eclipse-agent`):

```bat
:: Estado y diagnóstico
eclipse-agent status
eclipse-agent diagnostics

:: Voz
eclipse-agent say --text "Hola, soy Eclipse." --execute
eclipse-agent listen --seconds 4 --execute
eclipse-agent wake-loop --iterations 1 --execute

:: Comando ya transcrito (sin micrófono)
eclipse-agent wake-command --text "Eclipse, abre Instagram en el navegador"

:: Planificación y ruteo de acciones
eclipse-agent plan --instruction "Reproduce El lado oscuro en YouTube Music y abre Instagram"
eclipse-agent route-plan --provider deepseek --instruction "¿Qué hay en mi pantalla?"

:: Control de escritorio (Windows)
eclipse-agent open-app --app "Notepad"
eclipse-agent list-windows
eclipse-agent screenshot --output captura.png --execute
eclipse-agent type-text --text "hola" --confirmed

:: Notificaciones
eclipse-agent notifications-mode --mode game --minutes 60
eclipse-agent notifications-summary --mark-announced
eclipse-agent notifications-listen --seconds 30

:: Bridge a agentes de código (Claude Code / Gemini / Codex)
eclipse-agent coding-prompt --agent "Claude Code" --project C:\ruta --idea "Implementa..."
```

El flujo objetivo es:

```txt
daemon always-on
  -> wake word local
  -> transcripción local
  -> (visión de pantalla si hace falta)
  -> razonamiento del agente (local o DeepSeek)
  -> acción segura o borrador
  -> confirmación humana
  -> respuesta hablada
  -> memoria / log
```

## Capacidades

- **Wake word** local con openwakeword (`hey_jarvis` por defecto; soporta un modelo
  `Eclipse` propio entrenable, con fallback seguro mientras no pase evaluación).
- **Transcripción** local con faster-whisper.
- **Síntesis de voz** con SAPI de Windows.
- **Notificaciones**: captura, reglas de foco/juego/privado, resúmenes y borradores de
  respuesta, persistidas en SQLite.
- **Control de escritorio**: lanzar apps, listar ventanas, capturas de pantalla y tipeo
  nativo, a través de una capa de abstracción de plataforma (PAL) de Windows.
- **Automatización web** opcional vía `agent-browser`.
- **Visión** de pantalla bajo demanda con un modelo multimodal local.
- **Planificador híbrido**: reglas deterministas rápidas + capa LLM (local o DeepSeek) para
  instrucciones complejas.
- **Seguridad**: draft-first, confirmaciones para acciones sensibles y redacción de
  ventanas sensibles en capturas.

## Almacenamiento local

Eclipse guarda su estado bajo `%LOCALAPPDATA%\eclipse-agent\` (notificaciones y telemetría
en SQLite).

## Arquitectura

Eclipse usa una **capa de abstracción de plataforma (PAL)** para todo lo nativo de Windows
(ventanas, input, captura, lanzador, notificaciones, voz, daemon), un **planificador
provider-agnostic** y un **router de herramientas** con gates de seguridad. Ver
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) para el detalle técnico y
[`docs/SECURITY.md`](docs/SECURITY.md) para el modelo de seguridad.

## Desarrollo

```bat
.venv\Scripts\python -m pytest      :: tests
.venv\Scripts\python -m ruff check src tests   :: lint
```

## Licencia

MIT. Ver [`LICENSE`](LICENSE).
