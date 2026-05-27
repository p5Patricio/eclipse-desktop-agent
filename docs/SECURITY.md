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
- Logs de intención, plan, herramienta, resultado y confirmación.
- Kill switch global.
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

## OpenClaw

OpenClaw solo se evaluará:

- En VM, contenedor o usuario separado.
- Con credenciales de prueba.
- Sin exponerlo a internet durante la fase inicial.
- Con logs activados.
- Con revisión de plugins/tools antes de habilitarlos.

## Política de privacidad inicial

Por defecto:

- No grabar audio continuamente.
- No guardar screenshots salvo confirmación.
- No enviar pantalla completa si basta con texto o región reducida.
- No persistir mensajes privados completos si solo se necesita un resumen.
- Permitir borrar memoria local.

## Checklist antes de implementar una tool

- [ ] ¿La acción es reversible?
- [ ] ¿Puede afectar privacidad, dinero, reputación o archivos?
- [ ] ¿Requiere confirmación?
- [ ] ¿Está en allowlist?
- [ ] ¿Qué se registra?
- [ ] ¿Cómo se revierte o detiene?
- [ ] ¿Cómo se prueba sin dañar datos reales?
