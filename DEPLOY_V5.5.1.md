# Deploy v5.5.1 — La Vinoteca 206 + CAV Rendered Catalog Hotfix

Base requerida: **v5.5.0 Price Contexts & La Vinoteca**.

## Objetivo

Este hotfix corrige los dos fallos observados en la primera ejecución real de v5.5.0:

1. **La Vinoteca** devolvía HTTP `206` al endpoint VTEX para el rango `0-49`. `206 Partial Content` es una respuesta HTTP exitosa y el cuerpo JSON del rango debe procesarse, no tratarse como error.
2. **CAV** entregaba 25 productos y luego repetía la misma página porque el HTML inicial contiene bloques editoriales estáticos. El listado principal se renderiza por JavaScript; el collector ahora usa Playwright y extrae preferentemente los hits del buscador client-side.

## Cambios

### La Vinoteca

- acepta `200` y `206` como respuestas válidas;
- mantiene `416` como fin de rango;
- procesa el JSON exactamente igual para `200/206`;
- lee `Content-Range` cuando está disponible para detectar el final del catálogo;
- los logs muestran el HTTP real y, si existe, el total anunciado por VTEX.

Log esperado:

```text
La Vinoteca VTEX página 1: HTTP=206, 50 registros, total=..., catálogo_anunciado=...
La Vinoteca VTEX página 2: HTTP=206, ...
```

### CAV

- cambia de `requests`/HTML SSR a Playwright;
- espera el listado client-side;
- extrae preferentemente `.ais-Hits-item` / `.ais-InfiniteHits-item`;
- excluye de la paginación los bloques editoriales repetidos de Ofertas, Destacados, Liquidación y Recomendados;
- bloquea imágenes, fuentes, media y trackers con la infraestructura ya existente para reducir carga;
- conserva el límite global de 25 minutos;
- si solo aparecen los bloques estáticos, si se repite una página o si no existe una señal confiable de final, la captura se marca como no confiable y **no se persiste**;
- CAV sigue en `diagnostic_mode=true` y `comparison_enabled=false`.

Log esperado:

```text
CAV diagnóstico renderizado página 1: HTTP=200, modo=algolia_hits, hits=48, productos=..., nuevos=..., total=...
CAV diagnóstico renderizado página 2: HTTP=200, modo=algolia_hits, ...
...
```

Si el router de CAV trata `p=0` y `p=1` como alias, puede aparecer una sola vez:

```text
CAV diagnóstico: p=0 y p=1 parecen alias; se prueba la página siguiente.
```

Eso no es un error por sí solo.

## Base de datos

**No hay migraciones nuevas.**

Alembic debe permanecer en:

```text
0009_price_contexts
```

## Aplicación

1. Haz respaldo del repositorio. No es necesario modificar PostgreSQL para este hotfix.
2. Copia el contenido de `v5.5.1-lavinoteca-cav-hotfix/` sobre la raíz de tu proyecto v5.5.0.
3. Reemplaza los archivos existentes.
4. Commit + push.
5. Espera el deploy exitoso de Railway.
6. Haz **un solo Run now** para validar ambos collectors.

## Validación en Railway

Confirma primero:

```text
Monitor de Licores v5.5.1 · La Vinoteca 206 + CAV Rendered Catalog Hotfix
```

La Vinoteca debe dejar de fallar por `HTTP 206`.

CAV debe dejar de mostrar inmediatamente:

```text
paginación repetida detectada; fin seguro
25 productos
BROKEN
```

Si CAV falla de nuevo, conserva el log completo de sus líneas `CAV diagnóstico renderizado...`; el hotfix está diseñado para fallar de forma explícita antes de persistir una cobertura falsa.

## Rollback

Si necesitas volver atrás, restaura los tres archivos de aplicación de v5.5.0:

- `app/collectors/lavinoteca.py`
- `app/collectors/cav.py`
- `app/version.py`

No hay downgrade de base de datos asociado.
