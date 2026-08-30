# v5.9.2 — Expansion Consolidation

Esta versión no agrega tiendas ni modifica collectors. Convierte la fase posterior a la expansión en una auditoría reproducible.

## Qué revisa

- últimas 3 ejecuciones de La Koka, El Brindis, Rancho Wines, Licores.cl, Central Vinos y Licores y Tienda de Vinos La Reina;
- estado HEALTHY/DEGRADED/BROKEN;
- variación del número de productos;
- canonicalización y Data Quality;
- matches cerca del umbral del 86% y cola de revisión;
- tiempos cerca del timeout;
- brechas de precio >=2,5x;
- actividad del historial de precios y tamaño PostgreSQL.

## Veredictos

- `STABLE`: las seis fuentes cumplen los criterios de consolidación.
- `WATCH`: hay historial suficiente pero una o más fuentes requieren observación.
- `NOT_READY`: todavía no existen los ciclos suficientes.

Telegram: `/auditoria`.
