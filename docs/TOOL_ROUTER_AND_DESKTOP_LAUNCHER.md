# ToolRouter y lanzador de apps de Windows

## Objetivo

Conectar el `ActionPlan` de Eclipse con herramientas locales concretas, empezando por
acciones seguras:

- Abrir apps instaladas (accesos directos del Menú Inicio).
- Abrir URLs / web apps en el navegador por defecto.
- Preparar búsquedas web.
- Capturar pantalla.
- Bloquear acciones de riesgo medio/alto hasta que haya confirmación.

## Flujo

```txt
Instruction
  -> create_action_plan(...)
  -> ToolRouter.route_plan(...)
  -> safety gate (evaluate_risk + confirmación)
  -> NativeMCPClient / MCP servers / browser_automation
```

## Componentes implementados

| Archivo | Responsabilidad |
|---|---|
| `src/eclipse_agent/tool_router.py` | Rutea `PlannedAction` a tools locales con dry-run por defecto. Incluye `NativeMCPClient` con tools nativas (`open_url`, `google_search`, `open_desktop_app`, `capture_screenshot`). |
| `src/eclipse_agent/pal/windows/launcher.py` | `WindowsAppLauncher` descubre accesos directos `.lnk` del Menú Inicio y abre apps con `os.startfile`. |
| `src/eclipse_agent/browser_automation.py` | Prepara comandos `agent-browser` para open/search/snapshot. |
| `src/eclipse_agent/main.py` | Expone `plan` y `route-plan` para probar el ruteo desde CLI. |

`route-plan` y `plan` usan el `NativeMCPClient` por defecto cuando no se pasa
`--mcp-config`, así que rutean acciones de navegador/escritorio sin configuración extra.

## Seguridad

- **Dry-run por defecto**: no abre apps ni navegador sin `--execute`.
- **Sin shell interpolation**: los comandos se construyen como `tuple[str, ...]`.
- **Allowlist de apps de escritorio**: solo `browser`, `terminal`, `files` se aceptan como
  alias genéricos; targets ambiguos o con tokens de shell se rechazan.
- Las acciones de riesgo medio requieren `--confirmed`; las de alto riesgo siguen
  bloqueadas para ejecución real.

## Ejemplo

```bat
eclipse-agent route-plan --instruction "Reproduce El lado oscuro en YouTube Music, también abre Instagram en el navegador"
```

Salida esperada en dry-run:

```txt
Eclipse tool routing:
- action-1 [prepared] desktop.open_app: Prepared desktop launch for YouTube Music...
- action-2 [prepared] native.open_url: Prepared MCP tool call; draft mode did not execute it.
```

## Descubrimiento de apps en Windows

`WindowsAppLauncher` recorre las carpetas del Menú Inicio:

```txt
%ProgramData%\Microsoft\Windows\Start Menu\Programs
%APPDATA%\Microsoft\Windows\Start Menu\Programs
```

Busca el `.lnk` por nombre (exacto o por substring), resuelve su `TargetPath` con
`WScript.Shell` y abre la app con `os.startfile`. Las URLs se abren en el navegador por
defecto.

## Limitación actual

El ruteo abre/prepara la app o URL, pero todavía no opera dentro de la app (por ejemplo,
buscar y reproducir una canción específica dentro de YouTube Music). Ese adapter siguiente
puede construirse con `agent-browser` o con UI Automation de Windows:

1. Enfocar la ventana o web app.
2. Buscar el contenido.
3. Elegir el resultado correcto.
4. Ejecutar la acción (play).
5. Verificar el estado.
