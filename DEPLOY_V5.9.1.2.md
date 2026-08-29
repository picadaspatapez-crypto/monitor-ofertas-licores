# Deploy v5.9.1.2 — Vinos La Reina 202 Resilience

## Problema corregido
Railway comenzó a recibir `HTTP 202` en las categorías públicas de Tienda de Vinos La Reina. El helper HTTP aceptaba cualquier status <400 como documento parseable, por lo que el 202 terminaba como `tarjetas=0 / productos=0` y el collector fallaba.

## Estrategia
1. HTTP normal sigue siendo la ruta primaria.
2. `200` solo se acepta como catálogo cuando contiene markup de producto.
3. `202` o `200` sin productos provoca un único reintento HTTP con `Cache-Control: no-cache` y cache-buster.
4. Si el reintento sigue sin catálogo, se activa Chromium/Playwright de forma lazy únicamente para esa página.
5. `404` después de una página válida sigue siendo fin normal de paginación y no despierta el navegador.
6. Si Chromium tampoco obtiene productos, los guards existentes siguen cerrando el collector sin persistir basura.

## Archivos
- `app/collectors/http_catalog.py`
- `app/collectors/vinoslareina.py`
- `app/version.py`
- `tests/test_version.py`
- `tests/test_v5912_vinos_la_reina_resilience.py`

No hay migraciones de base de datos.

## Deploy
Aplicar sobre v5.9.1.1, commit/push y esperar Railway verde. Ejecutar un solo `Run now` y revisar específicamente las líneas de `Tienda de Vinos La Reina`. Si HTTP vuelve a responder 202, debe aparecer el reintento y, de ser necesario, `fuente=playwright-fallback`.
