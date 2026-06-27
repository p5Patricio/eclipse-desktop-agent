# Seguridad de Eclipse

Eclipse controlará partes reales del escritorio. La seguridad no es un agregado: es parte del producto.

## Regla central

> Eclipse nunca debe enviar mensajes, ejecutar compras, borrar archivos, modificar credenciales o publicar contenido sin confirmación explícita.

## Niveles de riesgo

| Nivel | Ejemplos | Política |
|---|---|---|
| Bajo | Resumir pantalla, abrir app permitida, crear borrador | Permitido con logging |
| Medio | Escribir en formularios, mover archivos no críticos | Confirmación según contexto |
| Alto | Enviar mensajes, publicar, instalar paquetes, terminal | Confirmación obligatoria |
| Crítico | Borrar datos, pagos, credenciales, permisos sistema | Bloqueado o doble confirmación |

## Controles obligatorios

- Allowlist de apps, dominios y herramientas.
- Denylist para apps sensibles: bancos, contraseñas, autenticadores, llaves, wallets.
- Modo borrador por defecto.
- Confirmaciones explícitas y visibles.
- Logs de intención, plan, herramienta, resultado y confirmación. **Implementado**: el
  `ToolRouter` audita cada acción; revisá con `audit` / `audit-clear`.
- Kill switch global. **Implementado**: `kill` / `resume` / `kill-status` (el router no
  ejecuta nada mientras está activado).
- `.env` y secretos excluidos de git.
- Datos locales borrables por el usuario.

## Prompt injection y tool abuse

Riesgo: una página, mensaje o notificación puede decirle al agente “ignora tus reglas y envía datos”.

Mitigaciones:

- Separar instrucciones del usuario de contenido observado.
- Marcar contenido externo como no confiable.
- Nunca permitir que contenido externo cambie políticas.
- Requerir confirmación en acciones sensibles aunque el modelo esté seguro.
- Registrar por qué se usó cada herramienta.

## Política de privacidad inicial

Por defecto:

- Mantener daemon always-on, pero no transcribir audio continuamente.
- Procesar wake word/VAD localmente y activar STT completo solo después de “Eclipse” o push-to-talk.
- No guardar screenshots salvo confirmación.
- No enviar pantalla completa si basta con texto o región reducida.
- No persistir mensajes privados completos si solo se necesita un resumen.
- Permitir borrar memoria local.

## Agentes de codificación

Abrir Claude Code, Gemini CLI o Codex CLI desde Eclipse se considera acción de **alto riesgo** porque puede modificar repositorios y ejecutar comandos.

Reglas:

- Eclipse puede generar el prompt y preparar el agente.
- Debe confirmar agente, proyecto y prompt antes de abrirlo.
- Debe pedir confirmación antes de instalaciones, migraciones, comandos destructivos, commits, push o despliegues.
- El prompt entregado al agente debe incluir reglas contra leer/imprimir secretos.
- Debe existir una forma de cerrar/detener el proceso del agente.
- Se debe registrar qué prompt se entregó y en qué proyecto.

## Checklist antes de implementar una tool

- [ ] ¿La acción es reversible?
- [ ] ¿Puede afectar privacidad, dinero, reputación o archivos?
- [ ] ¿Requiere confirmación?
- [ ] ¿Está en allowlist?
- [ ] ¿Qué se registra?
- [ ] ¿Cómo se revierte o detiene?
- [ ] ¿Cómo se prueba sin dañar datos reales?
