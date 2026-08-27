# Deploy v5.9.0.2

Base: v5.9.0.1.

## Cambios

- Parser WooCommerce específico para El Brindis, orientado a URL de producto y compatible con estructuras tipo Flatsome (`p.name.product-title`, `woocommerce-loop-product__title`, etc.).
- Extracción semántica de precios: `ins` como precio actual y `del` como precio normal cuando están presentes.
- Validación de cardinalidad: si el HTML contiene varios enlaces de producto pero se parsea menos del 50%, la categoría falla cerrada y no se persiste una captura falsa.
- HTTP 404 después de una o más páginas válidas se interpreta como fin natural de paginación.

## Despliegue

1. Aplicar el hotfix sobre v5.9.0.1.
2. Commit y push.
3. Esperar Build/Deploy/Healthcheck verde.
4. Ejecutar un solo `Run now`.
5. Revisar logs de El Brindis.

Esperado:

```text
El Brindis whisky página 1: HTTP=200, tarjetas≈20-30, productos≈20-30, ...
El Brindis whisky página 2: HTTP=200, ...
El Brindis whisky: fin confirmado por HTTP 404 tras N páginas válidas.
...
El Brindis  HEALTHY  productos=...
```

No se requiere Alembic; el head permanece en `0012_commercial_intelligence`.
