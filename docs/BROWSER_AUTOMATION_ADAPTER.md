# Browser Automation Adapter

## Objetivo

Eclipse necesita una capa de navegador controlada para abrir páginas, buscar información, leer snapshots semánticos y preparar interacciones como escribir mensajes o formularios sin enviar nada hasta confirmar.

La primera implementación usa `agent-browser` como backend principal porque está diseñado para agentes y puede trabajar con sesiones, allowlists de dominio y políticas de acción.

## Cómo entra el repo de Vercel

El repo que mencionaste es `vercel-labs/agent-browser`. En Eclipse no lo metemos como código copiado dentro del repo. Lo usamos como binario/CLI externo:

```txt
Eclipse Planner
  -> ToolRouter
  -> BrowserInteractionLoop
  -> AgentBrowserAdapter
  -> agent-browser CLI de Vercel
  -> Chrome/Chromium controlado por CDP
```

La ventaja es que Eclipse no tiene que inventar clicks por coordenadas. Primero pide un snapshot con refs como `@e1`, luego prepara acciones como `click @e1` o `fill @e2 "texto"`.

## Estado actual

Implementado:

- `src/eclipse_agent/browser_automation.py`
- `AgentBrowserAdapter`
- `BrowserAutomationProfile`
- `BrowserAutomationRequest`
- `BrowserAutomationResult`
- `BrowserSnapshot` / `BrowserElement` parser para salida JSON real
- Validación de URLs `http/https`.
- Derivación automática de dominios permitidos desde la URL.
- Comandos `open`, `search`, `snapshot`, `click`, `fill`, `type` y `press` en modo dry-run.
- Política base en `config/agent-browser-policy.json`.
- Integración con `ToolRouter` para `open_web_app` y `browser_search`.
- `BrowserInteractionLoop` para `open -> snapshot -i` con `batch --json` y acciones activas con confirmación.

No implementado todavía:

- Selector automático de refs semánticas.
- Confirmaciones interactivas por voz/UI para click/fill/type.
- Fallback Playwright.
- Sesiones autenticadas controladas.

## Seguridad

Reglas del adapter:

- Solo acepta URLs `http` y `https`.
- Construye comandos como `tuple[str, ...]`, sin shell.
- Usa dry-run por defecto.
- Deriva `--allowed-domains` por tarea.
- Usa `config/agent-browser-policy.json` para permitir acciones pasivas y pedir confirmación en acciones activas.

Política base:

```json
{
  "default": "deny",
  "allow": ["open", "snapshot", "screenshot", "get", "wait", "tab"],
  "confirm": ["click", "fill", "type", "press", "keyboard", "upload"],
  "deny": ["cookies.clear", "storage.clear", "state.clear"]
}
```

## Ejemplo desde ToolRouter

```bat
eclipse-agent route-plan --instruction "Abre YouTube, Instagram y Messenger en el navegador"
```

## Ejemplo de snapshot e interacción

```bat
eclipse-agent browser-snapshot --url https://example.com
```

Dry-run:

```txt
agent-browser ... batch --json --bail 'open https://example.com' 'snapshot -i'
```

Después de obtener una ref del snapshot, por ejemplo `@e2`, una acción activa se prepara así:

```bat
eclipse-agent browser-action --kind fill --selector @e2 --text "mensaje borrador" --confirmed
```

Sin `--confirmed`, Eclipse bloquea la acción.

La automatización web es **opcional**. Para ejecución real instalá `agent-browser`
(`npm install -g agent-browser` y `agent-browser install` para descargar Chrome for
Testing) y agregá `--execute`. Si el binario no está, Eclipse prepara el comando en dry-run
sin fallar.

## Siguiente paso técnico

El scaffold de `BrowserInteractionLoop` ya existe, el navegador real ya fue probado con `example.com`, y el parser JSON ya reconoce refs como `e1`/`@e1`. El siguiente paso es selector automático de refs:

```txt
open URL
  -> snapshot -i --json
  -> parse BrowserElement refs
  -> selector decide action by semantic refs
  -> safety gate
  -> click/fill/type only with confirmation
  -> snapshot/screenshot verification
```

Esto permitirá tareas como:

- Buscar una canción dentro de YouTube Music Web/PWA.
- Buscar especificaciones en páginas.
- Preparar respuestas en Instagram/Messenger sin enviarlas.
- Confirmar antes de enviar/publicar.
