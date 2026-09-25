# Roadmap — Monitor de Ofertas de Licores

## Estado actual: v6.0.0.3 — Watchlists + Source Resilience

La expansión v5.9 quedó implementada en dos olas y cerrada con una capa de auditoría operativa.

### Tiendas incorporadas en v5.9

Primera ola:
- La Koka
- El Brindis
- Rancho Wines

Segunda ola:
- Licores.cl
- Central Vinos y Licores
- Tienda de Vinos La Reina

### v5.9.2 — Consolidación

Objetivos implementados:

1. Auditoría de las últimas 3 ejecuciones por tienda nueva.
2. Estabilidad de cardinalidad del catálogo (spread de productos).
3. HEALTHY/DEGRADED/BROKEN por ventana de ciclos.
4. Cobertura de canonicalización y Data Quality.
5. Matches aceptados cerca del umbral del 86% y revisiones pendientes.
6. Duración promedio y detección de ejecuciones cercanas al timeout.
7. Brechas extremas de precio (>=2,5x) en comparables activos.
8. Observaciones históricas de 7 días vs los 7 días anteriores.
9. Tamaño real de PostgreSQL cuando el motor lo permite.
10. Comando Telegram `/auditoria` y reporte automático deduplicado.

La auditoría considera `STABLE` una tienda sólo cuando dispone de suficientes ciclos recientes, no tiene fallos recientes, mantiene variación de catálogo acotada, canonicalización >=98% y bloqueo de calidad <=1%. No baja guards ni modifica históricos para forzar un resultado verde.

## Versiones completadas

- v5.3.x: Socomep y hardening El Mundo del Vino.
- v5.4.x: Catalog Intelligence & Reliability.
- v5.5.x: La Vinoteca, multiprecio y búsqueda web.
- v5.6.x: CAV público/personal y rankings contextuales.
- v5.7.x: Matching 2.0 y Data Quality Engine.
- v5.8.x: Commercial Intelligence 2.0, mínimos, radar y hardening de identidad.
- v5.9.0.x: expansión ola 1 y estabilización.
- v5.9.1.x: expansión ola 2 y estabilización.
- v5.9.2: consolidación de la expansión.

## v6.0.0 — Watchlists completado

Implementado:

- precio objetivo por producto;
- Opportunity Score mínimo configurable;
- condición de nuevo mínimo histórico;
- ventaja CAV contra mercado público;
- deduplicación y estado persistente reutilizando la infraestructura de favoritos;
- `/vigilar`, `/watchlist` y `/quitarwatch`.

## v6.0.0.1 — Source Resilience Hotfix

Estabilización operativa sin ampliar alcance funcional: CAV adapta su ruta de catálogo, La Vinoteca recupera ventanas VTEX 5xx por división adaptativa, Vinos La Reina refuerza su sesión Chromium y las fuentes externas conocidas pueden reutilizar el último snapshot HEALTHY como `STALE` ante caídas transitorias. No hay migraciones nuevas.

## v6.0.0.2 — CAV Route Recovery

Corrige la regresión de ruta de CAV y devuelve el collector a `/tienda`, conservando los guards de ruta/filtros y la recuperación STALE.

## v6.0.0.3 — WooCommerce Availability-Aware Guard

El parser compartido de El Brindis y Tienda de Vinos La Reina reconoce explícitamente tarjetas agotadas y las excluye del denominador de cobertura activa. Los agotados no se persisten y las tarjetas activas siguen protegidas por un guard fail-closed.

## Siguiente: v6.0.1 — Alertas configurables

### v6.0.1 — Alertas configurables
- reglas combinables por precio, score, mínimo histórico y ventaja;
- silenciamiento mientras no cambie la condición;
- resumen de watchlists alcanzadas.

### v6.0.2 — Dashboard avanzado
- salud de tiendas;
- históricos por producto y tienda;
- oportunidades del día;
- watchlists;
- Data Quality y matching pendiente.

### v6.0.3 — Analítica de compra/reventa
- sólo con costos verificables/configurados;
- margen bruto y neto;
- ROI;
- precio de salida configurable;
- evitar recomendaciones basadas en comisiones o costos inventados.

- v6.0.0.4: hotfix de 404 terminal en fallback Chromium de Vinos La Reina.
