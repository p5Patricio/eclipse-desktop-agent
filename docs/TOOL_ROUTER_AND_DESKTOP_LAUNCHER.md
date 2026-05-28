# ToolRouter y Desktop App Launcher

## Objetivo

Conectar el `ActionPlan` de Eclipse con herramientas locales concretas, empezando por acciones seguras:

- Abrir apps instaladas por `.desktop`.
- Abrir URLs con `AgentBrowserAdapter`.
- Preparar búsquedas web.
- Bloquear acciones de riesgo medio/alto hasta que exista confirmación.

## Flujo

```txt
Instruction
  -> create_action_plan(...)
  -> ToolRouter.route_plan(...)
  -> safety gate
  -> desktop_app_launcher / browser_automation / future tools
```

## Componentes implementados

| Archivo | Responsabilidad |
|---|---|
| `src/eclipse_agent/desktop_apps.py` | Descubre `.desktop`, parsea `Name`, `Exec`, `StartupWMClass` y construye comandos sin shell. |
| `src/eclipse_agent/tool_router.py` | Rutea `PlannedAction` a tools locales con dry-run por defecto. |
| `src/eclipse_agent/browser_automation.py` | Prepara comandos `agent-browser` para open/search/snapshot. |
| `src/eclipse_agent/main.py` | Expone `route-plan` para probar el ruteo desde CLI. |

## Seguridad

- Dry-run por defecto: no abre apps ni navegador si no se usa `--execute`.
- No usa shell interpolation; los comandos se construyen como `tuple[str, ...]`.
- Acciones de riesgo medio requieren `--confirmed`.
- Acciones de alto riesgo siguen bloqueadas para ejecución real hasta implementar launchers específicos y confirmaciones explícitas.

## Ejemplo

```bash
PYTHONPATH=src python -m eclipse_agent route-plan \
  --instruction "Reproduce El lado oscuro de Jarabe de Palo en YouTube Music, también abre Instagram y Messenger en el navegador."
```

Salida esperada en dry-run:

```txt
Eclipse tool routing:
- action-1 [prepared] desktop_app_launcher: Prepared desktop launch for YouTube Music...
- action-2 [prepared] browser_automation: Open web app in controlled browser session.
- action-3 [prepared] browser_automation: Open web app in controlled browser session.
```

## YouTube Music detectado

En la máquina actual existe un launcher:

```txt
/home/patodev/.local/share/applications/chrome-cinhimbnkkaeohfgghhklpknlkffjgod-Default.desktop
```

Campos relevantes:

```txt
Name=YouTube Music
Exec=/opt/google/chrome/google-chrome --profile-directory=Default --app-id=cinhimbnkkaeohfgghhklpknlkffjgod
StartupWMClass=crx_cinhimbnkkaeohfgghhklpknlkffjgod
```

## Limitación actual

El bloque actual abre/prepara YouTube Music, pero todavía no busca ni reproduce la canción dentro de la app. Para eso falta el siguiente adapter:

1. Enfocar ventana de YouTube Music.
2. Buscar la canción.
3. Elegir resultado correcto.
4. Dar play.
5. Verificar estado de reproducción.

Ese adapter puede construirse con accesibilidad, navegación web controlada o `agent-browser`.
