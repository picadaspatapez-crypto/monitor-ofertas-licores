# Sprint 04 — Productos maestros y normalización

## Objetivo

Preparar el sistema para comparar un mismo producto entre distintas tiendas sin romper el monitor actual.

## Decisión principal

Las tablas actuales se reutilizan:

- `products` representa publicaciones concretas de tienda (`store_products`).
- `price_observations` representa el historial inmutable (`price_history`).

No se duplican esas tablas.

## Componentes incorporados

### `master_products`

Identidad común independiente de la tienda.

### `products.master_product_id`

Vincula cada publicación con su identidad maestra.

### `product_matches`

Registra cómo se realizó la coincidencia, su confianza y si requiere revisión.

### `app/matching/normalize.py`

Normaliza texto y volumen. En esta etapa solo realiza coincidencias conservadoras exactas sobre una clave normalizada.

## Flujo

```text
Nombre publicado por la tienda
        ↓
Normalización de texto y volumen
        ↓
normalized_key
        ↓
MasterProduct existente o nuevo
        ↓
Vínculo Product → MasterProduct
        ↓
Registro ProductMatch
```

## Alcance y límites

- No se usa coincidencia difusa todavía.
- No se asignan marcas mediante una lista cerrada.
- No se fusionan automáticamente productos con claves distintas.
- Los productos existentes se vincularán gradualmente en la siguiente ejecución del scraper.

## Criterio de término

El sprint se considera completo cuando:

1. Alembic aplica `0002_master_products`.
2. El monitor sigue procesando Licor3B.
3. Las publicaciones quedan asociadas a `master_products`.
4. El historial de precios continúa guardándose.
5. Telegram sigue funcionando sin cambios.
