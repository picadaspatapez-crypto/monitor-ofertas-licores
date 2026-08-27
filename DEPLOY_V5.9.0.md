# Deploy v5.9.0 — Store Expansion Wave 1

Base: v5.8.7 estable.

## Nuevas tiendas
- La Koka — Shopify, HTTP/JSON, sin navegador.
- El Brindis — catálogo WooCommerce público por categorías, HTTP-first.
- Rancho Wines — catálogo público paginado, HTTP-first.

## Despliegue
1. Respaldar PostgreSQL.
2. Aplicar el hotfix sobre v5.8.7.
3. Commit/push a GitHub.
4. Esperar Build + Deploy + Healthcheck verdes en Railway.
5. No hay migraciones nuevas: Alembic continúa en 0012_commercial_intelligence.
6. Ejecutar un único Run now.
7. Confirmar que las tres tiendas terminen HEALTHY/DEGRADED con productos plausibles y revisar /radar, /minimos y /quality.

## Rollback
Revertir los archivos del hotfix y redeploy. La versión no modifica el esquema de base de datos.
