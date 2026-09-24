# Deploy v6.0.0.2

1. Aplicar este hotfix sobre v6.0.0.1.
2. Commit/push a GitHub y desplegar en Railway.
3. No hay migración nueva; Alembic continúa en `0013_watchlists`.
4. Ejecutar un solo `Run now` y observar CAV.
5. Señal esperada: `Vinos / Tinto` debe producir páginas distintas y acumular bastante más de 11 productos; no debe repetirse el mismo `shard_total=11` en todas las categorías.
6. Si CAV responde 403/429 u otra falla externa, la recuperación STALE de v6.0.0.1 debe conservar el último snapshot HEALTHY.
