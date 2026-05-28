# Evaluación de agent-browser para Eclipse

`vercel-labs/agent-browser` es un CLI de automatización de navegador diseñado para agentes de IA. Para Eclipse, es una mejor primera opción que clicks visuales para tareas web porque expone una vista semántica de la página y permite actuar sobre referencias estables.

## Veredicto

| Pregunta | Respuesta |
|---|---|
| ¿Sirve para Eclipse? | Sí, especialmente para automatización web segura. |
| ¿Reemplaza todo el desktop automation? | No. Solo cubre navegador/web. |
| ¿Reemplaza Playwright? | Puede ser la primera capa para agentes; Playwright queda como fallback/control fino. |
| ¿Es compatible con nuestra filosofía? | Sí, si usamos allowlists, perfiles aislados y confirmaciones. |

## Qué aporta

- CLI nativo en Rust para controlar Chrome/Chromium.
- `snapshot` de árbol de accesibilidad con referencias como `@e1`, `@e2`.
- Acciones por referencia: click, fill, type, press, scroll, drag, upload.
- Screenshots normales y anotadas.
- Sesiones aisladas y perfiles persistentes.
- Domain allowlist.
- Action policy para permitir, denegar o confirmar acciones.
- Soporte de estado/cookies, tabs, frames, dialogs, network, HAR, console y traces.

## Por qué encaja mejor que clicks visuales

| Enfoque | Problema | Ventaja de agent-browser |
|---|---|---|
| Click por coordenadas | Frágil si cambia ventana, zoom o layout | Usa refs semánticas de accesibilidad |
| CSS selectors generados por LLM | Frágiles y requieren conocer DOM | El agente ve refs ya listas para usar |
| Playwright puro | Excelente para tests, más verboso para agentes | CLI pensado para loops de agentes |

## Limitaciones

- Solo controla navegador, no todo KDE/Linux.
- Sigue requiriendo seguridad: un LLM puede elegir la acción equivocada.
- Algunas páginas complejas o anti-bot pueden fallar.
- Para construir desde fuente pide Node 24+, pnpm 11+ y Rust. En nuestra máquina actual tenemos Node 22, así que conviene usar el binario publicado o actualizar Node si hace falta.
- Manejar sesiones autenticadas implica riesgo: cookies/state files pueden contener tokens.

## Integración propuesta

Crear un adapter en Eclipse:

```txt
Eclipse Agent
  -> SafetyPolicy
  -> BrowserTool
  -> AgentBrowserAdapter
  -> agent-browser CLI
  -> Chrome/Chromium session
```

El adapter debe:

1. Ejecutar `agent-browser` vía subprocess.
2. Capturar stdout/stderr estructurado cuando usemos `--json`.
3. Convertir comandos de Eclipse a acciones permitidas.
4. Usar `--allowed-domains` por tarea.
5. Usar `--action-policy` generado por Eclipse.
6. Guardar screenshots/logs solo si el usuario lo permite.

## Configuración segura inicial

Modo recomendado para pruebas:

```bash
agent-browser --session eclipse-mvp   --allowed-domains "example.com,localhost,127.0.0.1"   --action-policy ./config/agent-browser-policy.json   open https://example.com
```

Política base sugerida:

```json
{
  "default": "deny",
  "allow": ["open", "snapshot", "screenshot", "get", "wait", "tab"],
  "confirm": ["click", "fill", "type", "press", "keyboard", "upload"],
  "deny": ["cookies.clear", "storage.clear", "state.clear"]
}
```

La política exacta debe ajustarse tras probar cómo categoriza acciones el CLI.

## Decisión

Usar `agent-browser` como **candidato principal de automatización web para agentes** en Fase 3.

Mantener:

- Playwright para scripts deterministas y fallback.
- Herramientas desktop Linux para acciones fuera del navegador.
- OpenClaw como complemento de canales/plugins, no como controlador web principal.
