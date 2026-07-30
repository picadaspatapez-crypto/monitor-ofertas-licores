# Deploy v5.3.0 — Stabilization

Esta versión estabiliza los tres collectors incorporados en v5.2.

## Cambios

- Donde La Negra consulta primero la Store API pública de WooCommerce y pagina el catálogo global.
- Si la API no está disponible, Donde La Negra usa Playwright como respaldo y acepta el control de mayoría de edad.
- Se corrige la ruta pública de Tequilas (`/categoria-producto/tequilas/`).
- La Barra usa categorías específicas vigentes, combina DOM con respuestas JSON/XHR y detecta mantenimiento para fallar rápido sin borrar históricos.
- Distribuidora La Modelo amplía el techo técnico a 180 páginas, manteniendo el límite global de 25 minutos.
- No hay migraciones ni variables obligatorias nuevas.

## Despliegue

1. Reemplazar el contenido del repositorio por esta versión.
2. Commit sugerido: `Release v5.3 stabilization`.
3. Mantener la región que dejó estables las cuatro tiendas anteriores.
4. Ejecutar `Run now` una sola vez.

## Logs esperados

```text
Donde La Negra Store API página 1/...
Resumen Donde La Negra: fuente=woocommerce_store_api
```

Para La Barra:

```text
La Barra whisky: HTTP=200, DOM=..., JSON=..., productos=...
```

Si el sitio está en mantenimiento:

```text
La Barra está temporalmente en mantenimiento; se conserva el catálogo histórico.
```
