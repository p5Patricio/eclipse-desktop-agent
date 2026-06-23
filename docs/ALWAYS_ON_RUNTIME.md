# Runtime always-on de Eclipse

## Decisión

Eclipse debe sentirse siempre disponible, pero el modo seguro **no** es transcribir todo lo
que suena en la habitación. El diseño es:

```txt
Daemon local always-on
  -> escucha wake word local y eventos del sistema
  -> activa STT completo solo tras wake word, push-to-talk o evento permitido
  -> responde por TTS
  -> vuelve a reposo
```

## Estado implementado

`wake_runtime.py` ya tiene un loop acotado para pruebas reales:

```txt
wake-loop
  -> graba una ventana corta para detectar la palabra de activación
  -> si la frase trae comando, lo ejecuta en pipeline seguro
  -> si solo escucha la palabra, graba una segunda ventana de comando
  -> intenta intents de notificaciones primero
  -> si no aplica, usa planner + ToolRouter en modo seguro/dry-run
  -> opcionalmente responde por TTS con --speak
```

`wake-efficient` usa openwakeword como detector liviano y solo arranca Whisper después de la
palabra de activación, para reducir CPU en reposo. `scripts\start_eclipse.bat` lanza este
modo con `hey_jarvis` por defecto.

## Impacto de recursos

| Modo | RAM en espera | CPU en espera | Comentario |
|---|---:|---|---|
| Push-to-talk | bajo | ~0% | Más barato y privado, menos Jarvis. |
| Wake word local | bajo/medio | bajo | Recomendado para la sensación Alexa/Jarvis. |
| STT continuo | alto | medio/alto | Evitar: más calor, batería y riesgo de privacidad. |

El uso fuerte de RAM/CPU ocurre cuando se activa Whisper para transcribir; el listener de
notificaciones de Windows es liviano en comparación.

## Política de privacidad

- Wake word y VAD corren localmente.
- No guardar audio crudo salvo modo debug explícito.
- Mostrar indicador cuando el STT completo esté activo.
- Permitir apagar el micrófono desde un kill switch.
- Registrar intención y resultado, no conversaciones privadas completas.

## Prueba real recomendada

```bat
:: El venv tiene faster-whisper instalado.
.venv\Scripts\eclipse-agent diagnostics
.venv\Scripts\eclipse-agent listen-status

:: Pipeline sin micrófono, como si STT ya hubiera transcrito.
.venv\Scripts\eclipse-agent wake-command --text "Eclipse, modo juego por una hora"
.venv\Scripts\eclipse-agent wake-command --text "Eclipse, dime qué llegó"

:: Preparar el loop sin tocar el micrófono.
.venv\Scripts\eclipse-agent wake-loop --iterations 1

:: Prueba real con micrófono (decí la palabra de activación + comando).
.venv\Scripts\eclipse-agent wake-loop --iterations 1 --wake-seconds 4 --execute --speak
```

Por seguridad, `wake-loop --execute` graba/transcribe audio, pero las acciones de
escritorio/navegador siguen en dry-run. Para ejecutar acciones de bajo riesgo se requiere
`--route-execute`; para riesgo medio, también `--confirmed`.
