# Runtime always-on de Eclipse

## Decisión

Eclipse debe sentirse siempre disponible, pero el modo seguro/recomendado no es transcribir todo lo que suena en la habitación. El diseño será:

```txt
Daemon local always-on
  -> escucha wake word local “Eclipse” y eventos del sistema
  -> activa STT completo solo tras wake word, push-to-talk o evento permitido
  -> responde por TTS
  -> vuelve a reposo
```

## Estado implementado

El MVP ya tiene un loop acotado `wake-loop` para pruebas reales:

```txt
wake-loop
  -> graba una ventana corta para detectar “Eclipse”
  -> si la frase viene con comando, lo ejecuta en pipeline seguro
  -> si solo escucha “Eclipse”, graba una segunda ventana de comando
  -> intenta intents de notificaciones primero
  -> si no aplica, usa planner + ToolRouter en modo seguro/dry-run
  -> opcionalmente responde por TTS con --speak
```

La detección inicial usa STT local en ventanas cortas con `faster-whisper`.
Esto permite probar el flujo completo sin APIs pagadas. Más adelante se puede
sustituir esa primera ventana por un hotword engine dedicado para reducir CPU.

## Impacto de recursos

| Modo | RAM en espera | CPU en espera | Disco | Comentario |
|---|---:|---|---:|---|
| Push-to-talk | 40–120 MB | ~0% | 500 MB–1.6 GB | Más barato y privado, menos Jarvis. |
| Wake word local | 80–250 MB | Bajo | 600 MB–1.8 GB | Recomendado para Alexa/Jarvis. |
| STT continuo | 800 MB–2.5 GB+ | Medio/alto | 500 MB–3 GB | Evitar: más calor, batería y privacidad. |

Notas:

- El listener de notificaciones por D-Bus es ligero comparado con audio/STT.
- El uso fuerte de RAM/CPU ocurre cuando se activa Whisper/faster-whisper para transcribir.
- El disco lo dominan modelos locales de STT/TTS, no el código de Eclipse.
- En laptop, conviene tener perfiles: `wake_word` enchufado/default y `push_to_talk` para batería/privacidad.

## Política de privacidad

- Wake word y VAD deben correr localmente.
- No guardar audio crudo salvo modo debug explícito.
- Mostrar indicador cuando STT completo esté activo.
- Permitir apagar el micrófono desde un kill switch.
- Registrar intención y resultados, no conversaciones privadas completas por defecto.

## Primer work unit

1. `ActivationPolicy` para modelar `push_to_talk`, `wake_word` y `continuous_stt`.
2. CLI `status` para mostrar el modo activo.
3. CLI `resource-plan` para explicar recursos estimados.
4. Tests que protejan la decisión: default `wake_word`, no STT continuo.

## Prueba real recomendada

```bash
# Usar el venv porque ahí está faster-whisper.
PYTHONPATH=src venv/bin/python -m eclipse_agent diagnostics
PYTHONPATH=src venv/bin/python -m eclipse_agent listen-status

# Probar el pipeline sin micrófono, como si STT ya hubiera transcrito.
PYTHONPATH=src venv/bin/python -m eclipse_agent wake-command \
  --text "Eclipse, modo juego por una hora"
PYTHONPATH=src venv/bin/python -m eclipse_agent wake-command \
  --text "Eclipse, dime qué llegó"

# Preparar comandos de grabación sin tocar el micrófono.
PYTHONPATH=src venv/bin/python -m eclipse_agent wake-loop --iterations 1

# Prueba real con micrófono: decir “Eclipse, dime qué llegó”.
PYTHONPATH=src venv/bin/python -m eclipse_agent wake-loop \
  --iterations 1 \
  --wake-seconds 4 \
  --execute

# Si quieres que hable la respuesta.
PYTHONPATH=src venv/bin/python -m eclipse_agent wake-loop \
  --iterations 1 \
  --wake-seconds 4 \
  --execute \
  --speak
```

Por seguridad, `wake-loop --execute` sí graba/transcribe audio, pero las acciones
de escritorio/navegador siguen en dry-run. Para ejecutar acciones ruteadas de bajo
riesgo se requiere `--route-execute`; para acciones de riesgo medio, también
`--confirmed`.
