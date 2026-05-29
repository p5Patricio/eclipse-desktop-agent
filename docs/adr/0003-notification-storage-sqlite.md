# ADR 0003 — SQLite como store operacional de notificaciones

## Estado

Aceptado — 2026-05-29

## Contexto

Eclipse necesita guardar eventos pequeños de notificaciones, reglas por app,
estado de foco/juego/privado y cambios de lifecycle como `queued`, `announced`
o `replied`.

Se evaluó DuckDB porque es excelente en Python y muy rápido para análisis. La
documentación oficial de DuckDB lo describe como una base de datos SQL OLAP
in-process, integrada con Python y optimizada para consultas analíticas,
formatos como Parquet/CSV/JSON y workloads grandes. También documenta que la
escritura concurrente normal está pensada dentro de un solo proceso escritor.

SQLite, según su documentación oficial, es una base SQL in-process,
serverless, zero-configuration y transaccional; además Python incluye `sqlite3`
en la librería estándar.

## Decisión

Mantener **SQLite** como store operacional por defecto para notificaciones.

DuckDB queda como opción futura para:

- exportar historiales largos de notificaciones,
- analytics locales,
- resúmenes por día/semana/mes,
- consultas sobre Parquet/CSV si Eclipse agrega telemetría local opt-in.

## Motivos

| Criterio | SQLite | DuckDB |
|---|---|---|
| Workload actual | Mejor fit: OLTP pequeño, inserts/updates frecuentes | Mejor fit: OLAP/analytics |
| Dependencias | Incluido en Python | Requiere dependencia externa |
| Estado app local | Fuerte para tablas pequeñas y transacciones | Posible, pero no su foco principal |
| Concurrencia multi-proceso simple | Madura para uso local embebido | Más delicada para múltiples procesos escritores |
| Export/analytics futuro | Suficiente al inicio | Excelente opción complementaria |

## Consecuencias

- `NotificationStore` sigue usando `sqlite3`.
- No agregamos DuckDB al MVP, evitando peso y complejidad innecesaria.
- Si más adelante Eclipse necesita analytics pesados, se puede agregar un
  `NotificationAnalyticsStore` con DuckDB sin migrar el store operacional.
