# Deploy v4.4 — Performance Engine

Esta release mantiene las alertas inteligentes de v4.3 y acelera la recolección.

## Cambios

- Licor3B y Líquidos se ejecutan en paralelo con un máximo de 2 workers.
- Cada collector usa su propio navegador, contexto Playwright y sesión SQLAlchemy.
- Se bloquean imágenes, fuentes, multimedia y trackers comunes.
- `networkidle` deja de ser la espera principal.
- Las páginas continúan cuando aparecen tarjetas de productos o cambia el DOM.
- El scroll y «Cargar más» esperan crecimiento real del catálogo.
- Los logs y `scrape_runs.metrics_json` registran tiempos por fase.

## Railway

No hay migraciones ni variables obligatorias nuevas. Los valores opcionales son:

```env
COLLECTOR_WORKERS=2
BLOCK_BROWSER_RESOURCES=true
PRODUCT_WAIT_TIMEOUT_MS=8000
DOM_GROWTH_TIMEOUT_MS=4500
QUICK_SETTLE_MS=250
```

Para volver temporalmente al procesamiento secuencial:

```env
COLLECTOR_WORKERS=1
```

Para diagnosticar un sitio que dependa de imágenes o fuentes:

```env
BLOCK_BROWSER_RESOURCES=false
```

## Verificación esperada

Al comenzar:

```text
Monitor de Licores v4.4.0 · Performance Engine
Ejecución paralela: workers=2; bloqueo_recursos=sí
▶ Iniciando collector paralelo: Licor3B
▶ Iniciando collector paralelo: Líquidos
```

Al terminar:

```text
RESUMEN GLOBAL MULTI-TIENDA · PERFORMANCE
Duración de pared.........: ... s
Tiempo secuencial estimado: ... s
Tiempo ahorrado paralelo..: ... s
```
