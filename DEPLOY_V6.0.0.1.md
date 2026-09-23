# Deploy v6.0.0.1

1. Aplicar el hotfix sobre v6.0.0.
2. Commit/push a GitHub y desplegar en Railway.
3. No hay migración nueva; `alembic upgrade head` continúa en `0013_watchlists`.
4. Ejecutar un `Run now` y revisar específicamente CAV, La Vinoteca, La Modelo y Tienda de Vinos La Reina.
5. Resultado esperado ante una caída externa irrecuperable: `STALE`, no catálogo parcial persistido.
