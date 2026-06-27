# Orquestación multi-acción

## Objetivo

Eclipse debe aceptar una sola instrucción con varias acciones, dividirla en pasos seguros y ejecutar lo que pueda en paralelo sin perder control humano.

Ejemplo:

```txt
Usuario: Eclipse, reproduce El lado oscuro de Jarabe de Palo en YouTube Music;
también abre YouTube, Instagram y Messenger en el navegador.
```

Plan esperado:

1. Abrir YouTube Music y reproducir la canción solicitada.
2. Abrir YouTube en el navegador.
3. Abrir Instagram en el navegador.
4. Abrir Messenger en el navegador.

Las acciones independientes pueden iniciar en el mismo grupo de ejecución. Acciones que dependan de otra, por ejemplo “abre YouTube y busca X dentro del canal Y”, deben esperar a que el navegador esté listo.

## Capas necesarias

```txt
Natural-language instruction
  -> deterministic planner
  -> intent/action plan
  -> safety and cost policy
  -> tool router
  -> executor per tool/app
  -> verification
  -> spoken/text response
```

## Tipos de acción

| Acción | Ejemplo | Riesgo | Tool |
|---|---|---:|---|
| `play_media` | Reproduce una canción en YouTube Music | Bajo | `native.play_media` (abre la búsqueda en el navegador) |
| `open_web_app` | Abre YouTube/Instagram/Messenger | Bajo | Browser adapter / agent-browser |
| `browser_search` | Busca especificaciones en una página | Medio | agent-browser snapshots + refs semánticas |
| `system_control` | Sube el volumen, pausa, bloquea, batería | Bajo/Medio | `native.system_control` |
| `read_clipboard` | "¿Qué tengo copiado?" | Bajo | `native.read_clipboard` |
| `answer_question` | "¿Qué es la fotosíntesis?" | Bajo | `native.answer_question` |
| `set_reminder` | "Recordame en 10 minutos…" | Bajo | `native.set_reminder` |
| `add_routine` | "Cada mañana decime el resumen" | Bajo | `native.add_routine` |
| `remember_fact` / `recall_memory` | "Mi nombre es Patricio" / "¿Cómo me llamo?" | Bajo | `native.remember_fact` / `native.recall_memory` |
| `open_coding_agent` | Abre Claude Code/Gemini/Codex | Alto | Coding agent bridge |
| `unknown` | Petición ambigua | Medio | Pregunta aclaratoria |

## Reglas

- Separar instrucciones compuestas por “también”, “además”, “luego”, “después”.
- No dividir listas simples como “YouTube, Instagram y Messenger”.
- Ejecutar en paralelo solo acciones independientes y de bajo/medio riesgo.
- Confirmar acciones de alto riesgo antes de abrir agentes o ejecutar herramientas peligrosas.
- Verificar resultado: app abierta, página cargada, canción encontrada, borrador preparado, etc.
- Si una acción falla, Eclipse debe continuar con acciones independientes y reportar qué quedó pendiente.

## Primer work unit implementado

- `src/eclipse_agent/planner.py` define `ActionPlan`, `PlannedAction` y tipos de acción.
- CLI `plan` muestra cómo Eclipse dividiría una instrucción.
- Tests cubren reproducción en YouTube Music, apertura de varias web apps, búsqueda y agente de codificación.

## Segundo work unit implementado

- `src/eclipse_agent/tool_router.py` rutea acciones a tools locales con safety gates e
  incluye `NativeMCPClient` (open_url, google_search, open_desktop_app, capture_screenshot).
- `src/eclipse_agent/pal/windows/launcher.py` descubre apps del Menú Inicio (`.lnk`) y las
  abre con `os.startfile`.
- `src/eclipse_agent/browser_automation.py` prepara comandos `agent-browser` para navegador.
- CLI `route-plan` muestra qué tools se usarían y corre en dry-run por defecto.
- Tests cubren launcher de apps, browser URLs, búsqueda confirmada y bloqueo de alto riesgo.

## Lo que sigue

1. Implementar loop `snapshot -> semantic action -> verification`.
2. Implementar adapter de YouTube Music para buscar y reproducir.
3. Implementar verificación por ventana/título/accesibilidad/screenshot.
4. Agregar scheduler real para paralelismo, cancelación y timeouts.
5. Conectar el launcher de agentes de codificación a procesos reales con confirmación.
