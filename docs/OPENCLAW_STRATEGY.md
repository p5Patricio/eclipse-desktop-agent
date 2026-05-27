# Estrategia de OpenClaw para Eclipse

OpenClaw se tratará como alternativa y complemento, no como reemplazo inmediato de Eclipse.

## Decisión inicial

Construiremos un runtime propio para la experiencia principal de escritorio y evaluaremos OpenClaw para acelerar canales, plugins, automatizaciones y routing multi-agente.

## Por qué no reemplazar Eclipse con OpenClaw

| Necesidad de Eclipse | Razón para runtime propio |
|---|---|
| Wake word “Eclipse” como experiencia central | Queremos control total de UX y permisos. |
| Visión de pantalla y acciones locales | Deben estar diseñadas alrededor de seguridad desktop. |
| Confirmaciones humanas | La UX debe ser explícita y auditable. |
| Memoria personal local-first | Queremos política de privacidad propia. |
| Modularidad de proveedores | No depender de una sola plataforma. |

## Dónde sí puede ayudar OpenClaw

- Canales: Telegram, WhatsApp, Slack, Discord, etc.
- Plugins/tools ya existentes.
- Multi-agent routing.
- Skills reutilizables.
- Dashboard/control plane.
- Experimentos de voz o realtime.

## Opciones de integración

| Opción | Uso | Cuándo elegirla |
|---|---|---|
| Referencia | Solo estudiamos ideas | Si el runtime no encaja o es riesgoso |
| Bridge | Eclipse llama a OpenClaw para tareas concretas | Si canales/plugins funcionan bien |
| Plugin | Eclipse se expone como skill/tool de OpenClaw | Si OpenClaw tiene buen dashboard/canales |
| Reemplazo parcial | OpenClaw maneja agentes y Eclipse desktop tools | Solo si seguridad y DX son buenas |

## Experimento controlado

1. Instalar OpenClaw en entorno aislado.
2. Crear credenciales de prueba.
3. Activar solo un canal no sensible.
4. Probar una tool inocua.
5. Revisar logs y permisos.
6. Documentar riesgos.
7. Decidir integración.

## Criterios de adopción

OpenClaw puede entrar al proyecto si cumple:

- Se puede aislar de forma razonable.
- No obliga a usar credenciales personales en desarrollo.
- Permite auditar tools/plugins.
- No rompe el modelo safety-first de Eclipse.
- Aporta valor claro frente a implementar directo.

## Decisión provisional

> Eclipse será el producto principal. OpenClaw será evaluado como infraestructura auxiliar para canales y plugins.
