# Bridge de agentes de codificación

## Objetivo

Eclipse debe poder recibir una idea por voz, convertirla en un prompt estructurado y abrir un agente de codificación externo en el proyecto correcto.

Ejemplo:

```txt
Usuario: Eclipse, abre Claude Code en este proyecto y desarrolla una pantalla de login.
Eclipse: Preparé el prompt y detecté el proyecto. ¿Confirmas abrir Claude Code aquí?
Usuario: Sí.
Eclipse: Abre Claude Code, entrega el prompt y monitorea.
```

## Agentes iniciales

| Agente | Comando esperado | Aliases de voz |
|---|---|---|
| Claude Code | `claude` | Claude Code, Cloud Code, Clau Code |
| Gemini CLI | `gemini` | Gemini, Hemini, Gemini CLI |
| Codex CLI | `codex` | Codex, OpenAI Codex, Codex CLI |

## Prompt contract

Eclipse debe entregar al agente un prompt con:

- Nombre y ruta del proyecto.
- Idea original del usuario.
- Restricciones dictadas por el usuario.
- Reglas de seguridad: inspeccionar antes de editar, no tocar secretos, no ejecutar comandos destructivos sin confirmación.
- Expectativa de salida: archivos cambiados, pruebas ejecutadas y riesgos restantes.

## Seguridad

Los agentes de codificación son de alto riesgo porque pueden modificar código y ejecutar comandos.

Eclipse debe pedir confirmación antes de:

- Abrir el agente en un proyecto.
- Instalar dependencias.
- Ejecutar migraciones.
- Borrar archivos.
- Hacer commit/push.
- Desplegar.

## Primer work unit

1. Registry local de agentes y aliases.
2. Prompt builder determinístico.
3. CLI `coding-prompt` para probar la salida sin abrir procesos.
4. Después: launcher de terminal/proceso con allowlist y kill switch.
