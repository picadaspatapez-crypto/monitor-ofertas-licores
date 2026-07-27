# Especificación de Base de Datos

**Proyecto:** Monitor de Ofertas de Licores  
**Versión:** 0.1  
**Motor:** PostgreSQL  
**Gestión de esquema:** Alembic  
**Estado:** Diseño inicial

---

## 1. Objetivo

La base de datos debe permitir:

- registrar tiendas y categorías;
- representar productos normalizados;
- representar publicaciones concretas por tienda;
- conservar historial de precios y stock;
- registrar ejecuciones del scraper;
- detectar productos nuevos y cambios;
- evitar alertas duplicadas;
- comparar publicaciones entre tiendas;
- soportar análisis históricos y futuros modelos de inteligencia comercial.

La prioridad inicial es mantener trazabilidad y consistencia sin sobrediseñar el MVP.

---

## 2. Convenciones generales

### 2.1 Claves primarias

Todas las tablas usarán claves primarias enteras autoincrementales:

```text
id BIGSERIAL PRIMARY KEY
```

### 2.2 Fechas

Se utilizarán timestamps con zona horaria:

```text
TIMESTAMPTZ
```

Todas las fechas se guardarán en UTC.

### 2.3 Moneda

Los precios en pesos chilenos se almacenarán como enteros:

```text
price_clp INTEGER
```

No se usarán decimales para CLP.

### 2.4 Estados

Los estados se almacenarán inicialmente como texto restringido mediante `CHECK`, evitando enums rígidos durante el MVP.

### 2.5 Borrado

Se preferirá desactivar registros mediante campos como `is_active` antes que borrarlos físicamente.

### 2.6 Auditoría

Las tablas principales incluirán:

- `created_at`
- `updated_at`

### 2.7 Nombres

- nombres de tablas en plural;
- nombres de columnas en `snake_case`;
- claves foráneas con sufijo `_id`;
- índices con prefijo `ix_`;
- restricciones únicas con prefijo `uq_`;
- checks con prefijo `ck_`.

---

## 3. Diagrama lógico simplificado

```text
stores
  |
  +----< categories
  |
  +----< store_products >---- products
  |            |
  |            +----< price_observations
  |            |
  |            +----< stock_observations
  |            |
  |            +----< alerts
  |
  +----< scrape_runs
               |
               +----< scrape_errors

products
  |
  +----< product_matches
```

---

# 4. Tablas

## 4.1 stores

Representa una tienda monitoreada.

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `name` | VARCHAR(120) | No | Nombre visible |
| `slug` | VARCHAR(120) | No | Identificador interno |
| `base_url` | TEXT | No | URL base |
| `connector_key` | VARCHAR(120) | No | Clave del conector |
| `is_active` | BOOLEAN | No | Si debe monitorearse |
| `requires_browser` | BOOLEAN | No | Si requiere Playwright |
| `country_code` | CHAR(2) | No | Inicialmente `CL` |
| `currency_code` | CHAR(3) | No | Inicialmente `CLP` |
| `last_success_at` | TIMESTAMPTZ | Sí | Última revisión exitosa |
| `last_error_at` | TIMESTAMPTZ | Sí | Último error |
| `created_at` | TIMESTAMPTZ | No | Creación |
| `updated_at` | TIMESTAMPTZ | No | Modificación |

### Restricciones

```text
uq_stores_slug
uq_stores_connector_key
```

### Índices

```text
ix_stores_is_active
```

---

## 4.2 categories

Representa una categoría descubierta dentro de una tienda.

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `store_id` | BIGINT | No | Tienda |
| `name` | VARCHAR(255) | No | Nombre fuente |
| `normalized_name` | VARCHAR(255) | Sí | Nombre común |
| `source_url` | TEXT | No | URL de categoría |
| `source_key` | VARCHAR(255) | Sí | Identificador de la tienda |
| `is_active` | BOOLEAN | No | Si sigue disponible |
| `first_seen_at` | TIMESTAMPTZ | No | Primera detección |
| `last_seen_at` | TIMESTAMPTZ | No | Última detección |
| `created_at` | TIMESTAMPTZ | No | Creación |
| `updated_at` | TIMESTAMPTZ | No | Modificación |

### Relaciones

```text
categories.store_id -> stores.id
```

### Restricciones

```text
uq_categories_store_url
```

Única por:

```text
(store_id, source_url)
```

### Índices

```text
ix_categories_store_id
ix_categories_is_active
```

---

## 4.3 brands

Catálogo normalizado de marcas.

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `name` | VARCHAR(255) | No | Nombre oficial |
| `normalized_name` | VARCHAR(255) | No | Nombre normalizado |
| `country_code` | CHAR(2) | Sí | País de origen |
| `created_at` | TIMESTAMPTZ | No | Creación |
| `updated_at` | TIMESTAMPTZ | No | Modificación |

### Restricciones

```text
uq_brands_normalized_name
```

---

## 4.4 products

Representa la identidad normalizada de un producto, independiente de la tienda.

Ejemplo:

```text
Johnnie Walker Black Label 750 ml
```

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `brand_id` | BIGINT | Sí | Marca normalizada |
| `normalized_name` | VARCHAR(500) | No | Nombre normalizado |
| `category_name` | VARCHAR(120) | Sí | Categoría común |
| `subcategory_name` | VARCHAR(120) | Sí | Subcategoría |
| `volume_ml` | INTEGER | Sí | Volumen |
| `alcohol_percentage` | NUMERIC(5,2) | Sí | Graduación alcohólica |
| `vintage_year` | SMALLINT | Sí | Añada |
| `country_code` | CHAR(2) | Sí | País de origen |
| `ean` | VARCHAR(20) | Sí | Código de barras |
| `manufacturer_sku` | VARCHAR(120) | Sí | Código del fabricante |
| `is_pack` | BOOLEAN | No | Si es pack |
| `units_per_pack` | INTEGER | Sí | Unidades del pack |
| `status` | VARCHAR(30) | No | Estado |
| `created_at` | TIMESTAMPTZ | No | Creación |
| `updated_at` | TIMESTAMPTZ | No | Modificación |

### Estados permitidos

```text
active
review
archived
```

### Restricciones

```text
ck_products_volume_positive
ck_products_alcohol_range
ck_products_units_per_pack_positive
```

### Índices

```text
ix_products_normalized_name
ix_products_brand_id
ix_products_ean
ix_products_category_name
```

### Restricciones únicas

El campo `ean` será único solo cuando no sea nulo.

Índice parcial recomendado:

```sql
CREATE UNIQUE INDEX uq_products_ean_not_null
ON products (ean)
WHERE ean IS NOT NULL;
```

---

## 4.5 store_products

Representa una publicación concreta en una tienda.

Una misma identidad de producto puede tener varias publicaciones, una por tienda.

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `store_id` | BIGINT | No | Tienda |
| `product_id` | BIGINT | Sí | Producto normalizado |
| `category_id` | BIGINT | Sí | Categoría fuente |
| `source_name` | VARCHAR(600) | No | Nombre original |
| `source_url` | TEXT | No | URL del producto |
| `canonical_url` | TEXT | Sí | URL limpia |
| `source_sku` | VARCHAR(255) | Sí | SKU de tienda |
| `source_ean` | VARCHAR(20) | Sí | EAN observado |
| `source_category` | VARCHAR(255) | Sí | Categoría original |
| `normalized_name` | VARCHAR(600) | Sí | Nombre normalizado |
| `current_price_clp` | INTEGER | No | Precio actual |
| `regular_price_clp` | INTEGER | Sí | Precio normal |
| `discount_percentage` | NUMERIC(6,3) | No | Descuento |
| `in_stock` | BOOLEAN | No | Disponibilidad |
| `stock_quantity` | INTEGER | Sí | Stock exacto |
| `image_url` | TEXT | Sí | Imagen |
| `promotion_text` | TEXT | Sí | Texto promocional |
| `first_seen_at` | TIMESTAMPTZ | No | Primera detección |
| `last_seen_at` | TIMESTAMPTZ | No | Última detección |
| `last_changed_at` | TIMESTAMPTZ | Sí | Último cambio |
| `is_active` | BOOLEAN | No | Sigue publicado |
| `created_at` | TIMESTAMPTZ | No | Creación |
| `updated_at` | TIMESTAMPTZ | No | Modificación |

### Relaciones

```text
store_products.store_id -> stores.id
store_products.product_id -> products.id
store_products.category_id -> categories.id
```

### Restricciones

```text
uq_store_products_store_url
```

Única por:

```text
(store_id, canonical_url)
```

### Checks

```text
ck_store_products_current_price_positive
ck_store_products_regular_price_positive
ck_store_products_stock_non_negative
ck_store_products_discount_range
```

### Índices

```text
ix_store_products_store_id
ix_store_products_product_id
ix_store_products_category_id
ix_store_products_is_active
ix_store_products_current_price
ix_store_products_last_seen_at
```

---

## 4.6 price_observations

Historial inmutable de precios.

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `store_product_id` | BIGINT | No | Publicación |
| `price_clp` | INTEGER | No | Precio observado |
| `regular_price_clp` | INTEGER | Sí | Precio normal |
| `discount_percentage` | NUMERIC(6,3) | No | Descuento |
| `promotion_text` | TEXT | Sí | Promoción |
| `observed_at` | TIMESTAMPTZ | No | Fecha de observación |
| `scrape_run_id` | BIGINT | Sí | Ejecución origen |

### Relaciones

```text
price_observations.store_product_id -> store_products.id
price_observations.scrape_run_id -> scrape_runs.id
```

### Checks

```text
ck_price_observations_price_positive
ck_price_observations_discount_range
```

### Índices

```text
ix_price_observations_store_product_time
ix_price_observations_observed_at
```

Índice compuesto recomendado:

```text
(store_product_id, observed_at DESC)
```

---

## 4.7 stock_observations

Historial de disponibilidad.

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `store_product_id` | BIGINT | No | Publicación |
| `in_stock` | BOOLEAN | No | Disponibilidad |
| `stock_quantity` | INTEGER | Sí | Cantidad |
| `observed_at` | TIMESTAMPTZ | No | Fecha |
| `scrape_run_id` | BIGINT | Sí | Ejecución origen |

### Índices

```text
ix_stock_observations_store_product_time
```

---

## 4.8 scrape_runs

Representa una ejecución de monitoreo por tienda.

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `store_id` | BIGINT | No | Tienda |
| `status` | VARCHAR(30) | No | Resultado |
| `started_at` | TIMESTAMPTZ | No | Inicio |
| `finished_at` | TIMESTAMPTZ | Sí | Fin |
| `duration_ms` | INTEGER | Sí | Duración |
| `pages_requested` | INTEGER | No | Páginas solicitadas |
| `pages_succeeded` | INTEGER | No | Páginas exitosas |
| `products_found` | INTEGER | No | Productos detectados |
| `products_created` | INTEGER | No | Nuevos |
| `products_updated` | INTEGER | No | Actualizados |
| `products_failed` | INTEGER | No | Fallidos |
| `price_changes` | INTEGER | No | Cambios de precio |
| `stock_changes` | INTEGER | No | Cambios de stock |
| `error_message` | TEXT | Sí | Resumen |
| `created_at` | TIMESTAMPTZ | No | Creación |

### Estados permitidos

```text
running
success
partial
failed
```

### Índices

```text
ix_scrape_runs_store_started
ix_scrape_runs_status
```

---

## 4.9 scrape_errors

Registra errores específicos de una ejecución.

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `scrape_run_id` | BIGINT | No | Ejecución |
| `error_type` | VARCHAR(120) | No | Tipo |
| `source_url` | TEXT | Sí | URL afectada |
| `source_key` | VARCHAR(255) | Sí | Identificador |
| `message` | TEXT | No | Mensaje |
| `details_json` | JSONB | Sí | Detalle técnico |
| `created_at` | TIMESTAMPTZ | No | Creación |

### Índices

```text
ix_scrape_errors_run_id
ix_scrape_errors_error_type
```

---

## 4.10 alerts

Historial de alertas generadas.

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `store_product_id` | BIGINT | No | Publicación |
| `alert_type` | VARCHAR(50) | No | Tipo |
| `status` | VARCHAR(30) | No | Estado |
| `channel` | VARCHAR(30) | No | Canal |
| `price_clp` | INTEGER | No | Precio alertado |
| `opportunity_score` | NUMERIC(6,3) | Sí | Puntaje |
| `estimated_margin` | NUMERIC(8,4) | Sí | Margen |
| `estimated_profit_clp` | INTEGER | Sí | Utilidad |
| `suggested_units` | INTEGER | Sí | Unidades |
| `reason` | TEXT | No | Motivo |
| `deduplication_key` | VARCHAR(255) | No | Clave anti-duplicados |
| `sent_at` | TIMESTAMPTZ | Sí | Fecha envío |
| `failed_at` | TIMESTAMPTZ | Sí | Fecha error |
| `error_message` | TEXT | Sí | Error |
| `created_at` | TIMESTAMPTZ | No | Creación |

### Tipos iniciales

```text
new_opportunity
price_drop
back_in_stock
high_score
daily_summary
technical_error
```

### Estados

```text
pending
sent
failed
suppressed
```

### Restricciones

```text
uq_alerts_deduplication_key
```

### Índices

```text
ix_alerts_store_product_id
ix_alerts_status
ix_alerts_created_at
```

---

## 4.11 product_matches

Registra la relación entre una publicación de tienda y un producto normalizado.

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `store_product_id` | BIGINT | No | Publicación |
| `product_id` | BIGINT | No | Producto |
| `confidence` | NUMERIC(6,3) | No | Confianza |
| `matching_method` | VARCHAR(50) | No | Método |
| `review_status` | VARCHAR(30) | No | Estado |
| `reviewed_by` | VARCHAR(120) | Sí | Revisor |
| `reviewed_at` | TIMESTAMPTZ | Sí | Fecha |
| `created_at` | TIMESTAMPTZ | No | Creación |

### Métodos

```text
ean
sku
exact_normalized
fuzzy
manual
```

### Estados

```text
automatic
pending_review
approved
rejected
```

### Restricciones

```text
uq_product_matches_store_product
```

---

## 4.12 opportunity_snapshots

Tabla futura para conservar el resultado de cada evaluación comercial.

### Columnas

| Columna | Tipo | Nulo | Descripción |
|---|---|---:|---|
| `id` | BIGSERIAL | No | Clave primaria |
| `store_product_id` | BIGINT | No | Publicación |
| `opportunity_score` | NUMERIC(6,3) | No | Puntaje |
| `market_price_clp` | INTEGER | Sí | Precio mercado |
| `expected_sale_price_clp` | INTEGER | Sí | Venta esperada |
| `estimated_cost_clp` | INTEGER | Sí | Costo total |
| `estimated_profit_clp` | INTEGER | Sí | Utilidad |
| `estimated_margin` | NUMERIC(8,4) | Sí | Margen |
| `risk_score` | NUMERIC(6,3) | Sí | Riesgo |
| `suggested_units` | INTEGER | Sí | Unidades |
| `recommendation` | VARCHAR(30) | No | Recomendación |
| `explanation_json` | JSONB | Sí | Factores |
| `evaluated_at` | TIMESTAMPTZ | No | Fecha |

Esta tabla no es obligatoria para la primera migración.

---

# 5. Reglas de negocio en la base de datos

## 5.1 Producto observado

Cada publicación debe tener:

- tienda;
- nombre fuente;
- URL;
- precio actual;
- estado de stock;
- fecha de última observación.

## 5.2 Historial inmutable

Las tablas `price_observations` y `stock_observations` no deben actualizarse. Cada revisión añade una nueva fila.

## 5.3 Detección de cambio

Se considera cambio de precio cuando:

```text
nuevo_precio != store_products.current_price_clp
```

Se considera baja cuando:

```text
nuevo_precio < store_products.current_price_clp
```

## 5.4 Producto desaparecido

Una publicación no encontrada durante una ejecución no debe eliminarse inmediatamente.

Política inicial:

- mantener `is_active = true` durante tres ejecuciones fallidas consecutivas;
- después marcar `is_active = false`;
- reactivar si vuelve a aparecer.

Para esto podrá añadirse:

```text
consecutive_misses INTEGER
```

en `store_products`.

## 5.5 Alertas duplicadas

La clave de deduplicación puede construirse como:

```text
store_product_id:alert_type:price_clp:stock_state
```

Ejemplo:

```text
482:price_drop:21990:true
```

## 5.6 Precio normal

Si el precio normal es menor que el precio actual, el registro debe marcarse como inconsistente y no utilizarse para calcular descuento.

---

# 6. Índices prioritarios para el MVP

Los siguientes índices son imprescindibles:

```text
store_products(store_id, canonical_url)
price_observations(store_product_id, observed_at DESC)
stock_observations(store_product_id, observed_at DESC)
scrape_runs(store_id, started_at DESC)
alerts(deduplication_key)
products(ean) WHERE ean IS NOT NULL
```

---

# 7. Retención de datos

Política inicial:

- productos y publicaciones: indefinidos;
- historial de precios: indefinido;
- historial de stock: indefinido;
- scrape runs: mínimo 12 meses;
- errores detallados: mínimo 90 días;
- alertas: indefinidas.

La retención podrá revisarse según costo y crecimiento.

---

# 8. Migraciones con Alembic

Toda modificación del esquema debe realizarse mediante migraciones.

Flujo:

```text
cambio de modelos
    |
    v
alembic revision --autogenerate
    |
    v
revisión manual
    |
    v
alembic upgrade head
```

Nunca se modificarán tablas manualmente en producción salvo emergencia documentada.

---

# 9. Primera migración recomendada

La primera migración debería crear:

1. `stores`
2. `categories`
3. `brands`
4. `products`
5. `store_products`
6. `scrape_runs`
7. `scrape_errors`
8. `price_observations`
9. `stock_observations`
10. `alerts`
11. `product_matches`

`opportunity_snapshots` puede esperar hasta que exista el motor de oportunidades.

---

# 10. Datos iniciales

La migración o script de bootstrap debe crear la tienda Licor3B:

```text
name: Licor3B
slug: licor3b
base_url: https://licor3b.cl/
connector_key: licor3b
is_active: true
requires_browser: false
country_code: CL
currency_code: CLP
```

Las demás tiendas se incorporarán cuando sus conectores estén listos.

---

# 11. Decisiones diferidas

Se posponen:

- tabla de usuarios;
- autenticación;
- compras y ventas reales;
- inventario propio;
- comisiones históricas de marketplaces;
- múltiples monedas;
- múltiples países;
- modelo predictivo;
- dashboard multiusuario.

---

# 12. Próximo paso técnico

Después de subir este documento:

1. crear modelos SQLAlchemy alineados con la primera migración;
2. instalar y configurar Alembic;
3. generar migración inicial;
4. aplicar migración en Railway;
5. adaptar el conector de Licor3B al nuevo esquema;
6. comprobar que las observaciones y ejecuciones se guarden correctamente.

No se debe crear una segunda tienda antes de completar estos pasos.

---

# Estado implementado en v4.3

La implementación productiva utiliza las tablas `stores`, `products`,
`master_products`, `product_matches`, `price_observations`, `scrape_runs` y
`alerts`. La migración `0004_smart_alerts` amplía `alerts` para que pueda
representar tanto cambios de productos como eventos generales de una tienda.

## alerts en v4.3

| Columna | Uso |
|---|---|
| `product_id` | Producto relacionado; puede ser nulo para resúmenes o fallos de collector |
| `store_id` | Tienda que originó la notificación |
| `scrape_run_id` | Ejecución que detectó el evento |
| `alert_type` | `price_drop`, `ranking_digest`, `collector_incident`, etc. |
| `status` | `pending`, `sent` o `failed` |
| `price` | Precio relacionado cuando corresponde; puede ser nulo |
| `reason` | Explicación legible del envío |
| `deduplication_key` | Clave única que impide duplicados |
| `payload_hash` | SHA-256 del contenido lógico del evento |
| `sent_at` | Fecha efectiva del envío |
| `failed_at` | Fecha del último fallo de Telegram |
| `error_message` | Error abreviado para diagnóstico y reintento |

La reserva se crea antes de llamar a Telegram. Un evento ya enviado no vuelve a
reservarse. Los eventos fallidos pueden reintentarse y una reserva pendiente
abandonada se libera después de 30 minutos.

## v4.7 · telegram_bot_state

Tabla pequeña de clave/valor usada por el bot interactivo para conservar el
siguiente `update_id` de Telegram. Evita reprocesar mensajes después de un
reinicio o redeploy del servicio `buscador-licores`.

| Campo | Uso |
|---|---|
| `key` | Identificador del estado, actualmente `telegram_search_next_update_id` |
| `value` | Próximo ID de actualización que debe solicitarse |
| `updated_at` | Fecha de actualización del offset |
