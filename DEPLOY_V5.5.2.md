# Deploy v5.5.2 — Pagination Boundary & CAV Sharded Catalog Hotfix

Base requerida: **v5.5.1 La Vinoteca 206 + CAV Rendered Catalog Hotfix**.

## Objetivo

Este hotfix corrige los dos límites reales observados en Railway después de v5.5.1:

1. **La Vinoteca** completa aproximadamente 996 productos y, al pedir el siguiente rango, VTEX puede volver a servir una página completa sin productos nuevos. Esa cola repetida es un final de catálogo, no un fallo del collector.
2. **CAV** llega a ~1000 productos y después solo conserva tarjetas editoriales/repetidas. El estado de URL (`idx`, `hPP`, `p`, `fR[...]`) corresponde al buscador client-side y la búsqueda global alcanza el límite de paginación; por eso ya no se recorre el índice global. Se divide la captura en shards por familia y, para Vinos, por categoría.

## Cambios

### La Vinoteca

- mantiene HTTP `200` y `206` como éxito;
- conserva HTTP `416` como fin válido;
- además de `Content-Range`, acepta `REST-Content-Range` y `X-VTEX-Content-Range` cuando un proxy VTEX expone el total con otro nombre;
- si VTEX clampa un rango posterior al total observable y devuelve una página sin URLs nuevas, lo registra como **fin terminal** en vez de `RuntimeError`;
- no rebaja la protección ante una repetición inesperada en medio del catálogo.

Log esperado al final:

```text
La Vinoteca VTEX página 20: HTTP=206, ... total=996
La Vinoteca VTEX fin confirmado por clamp terminal: rango 1000-1049, productos_unicos=996.
```

Si VTEX entrega un header de total interpretable, puede terminar una página antes y no aparecer el mensaje de clamp.

### CAV

La captura global se reemplaza por **catálogo segmentado**.

Familias alcohólicas:

- Licores
- Whisky
- Piscos
- Packs
- Cervezas

Vinos se subdivide inicialmente en:

- Tinto
- Ensamblaje Tinto
- Blanco
- Espumoso
- Bajos Y Sin Alcohol
- Ensamblaje Blanco
- Rosado
- Naranjo
- Sin Informacion

El collector además intenta descubrir nuevas facetas `wine_type.name` desde el HTML renderizado. Si aparecen categorías nuevas, se agregan como shards automáticamente.

Cada shard:

- usa su filtro `fR[...]` propio;
- pagina de forma independiente;
- termina cuando el frontend devuelve una cola sin URLs nuevas;
- tolera una sola ambigüedad `p=0` / `p=1`;
- tiene un máximo plausible para detectar que un filtro fue ignorado;
- debe terminar con señal explícita de fin;
- no persiste una captura si el agregado final queda bajo el mínimo de cobertura.

CAV sigue en:

```text
diagnostic_mode=true
comparison_enabled=false
```

No afecta el comparador público aunque falle.

## Base de datos

**No hay migraciones nuevas.**

Alembic debe permanecer en:

```text
0009_price_contexts
```

## Aplicación

1. Copia el contenido de `v5.5.2-pagination-sharding-hotfix/` sobre la raíz de tu proyecto v5.5.1.
2. Reemplaza archivos.
3. Commit + push.
4. Espera deploy exitoso en Railway.
5. Haz un único `Run now` de validación.

## Validación esperada

Inicio:

```text
Monitor de Licores v5.5.2 · Pagination Boundary & CAV Sharded Catalog Hotfix
```

La Vinoteca debe finalizar `HEALTHY` alrededor del total real, sin interpretar la cola VTEX como error.

CAV debe comenzar con una línea similar a:

```text
CAV diagnóstico segmentado: Vinos / Tinto, Vinos / Ensamblaje Tinto, ... Licores, Whisky, Piscos, Packs, Cervezas
```

Después se verán líneas por shard:

```text
CAV Vinos / Tinto página 1: ... nuevos_shard=...
...
CAV Vinos / Tinto: fin confirmado por cola sin productos nuevos (...)
CAV Licores página 1: ...
```

Al terminar debe quedar `HEALTHY` y con una cobertura agregada claramente superior al límite de ~1000 que frenó la consulta global.

## Rollback

Restaura estos archivos desde v5.5.1:

- `app/collectors/lavinoteca.py`
- `app/collectors/cav.py`
- `app/version.py`

No hay downgrade de base de datos.
