# Deploy v5.8.7 — PostgreSQL JSON DISTINCT Cross-store Hotfix

Base: v5.8.6.

## Causa corregida
La etapa cross-store cargaba `Product` mediante `SELECT DISTINCT products.*`. `products` contiene la columna JSON `data_quality_issues`; PostgreSQL no puede aplicar DISTINCT sobre `json` porque ese tipo no define operador de igualdad, produciendo:

`psycopg.errors.UndefinedFunction: could not identify an equality operator for type json`

## Solución
`products_observed_in_runs()` deja de hacer JOIN + DISTINCT sobre la fila completa y utiliza un `EXISTS` correlacionado contra `price_observations`. Así cada Product se obtiene una sola vez sin comparar columnas JSON.

## Despliegue
1. Aplicar el contenido del hotfix sobre v5.8.6.
2. Commit/push.
3. Esperar deployment HEALTHY.
4. Ejecutar un único Run now.
5. Confirmar que ya no aparezca `Etapa cross-store omitida por error`.
6. Probar `/radar` y `/minimos`.

No hay migraciones nuevas. Alembic permanece en `0012_commercial_intelligence`.
