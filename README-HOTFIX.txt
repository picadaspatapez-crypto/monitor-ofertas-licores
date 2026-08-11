v5.5.0 — PRICE CONTEXTS & LA VINOTECA
=====================================

BASE OBLIGATORIA: v5.4.0 Catalog Intelligence & Reliability.

Aplicación:
1. Haz respaldo de PostgreSQL y del repositorio.
2. Copia el CONTENIDO de este hotfix sobre la raíz del proyecto v5.4.0.
3. Reemplaza archivos cuando se solicite.
4. Commit + push.
5. Railway debe ejecutar `alembic upgrade head` y llegar a `0009_price_contexts`.
6. Ejecuta una corrida manual de validación.

La Vinoteca queda ACTIVA.
CAV queda en DIAGNÓSTICO y NO modifica el comparador público.

Consulta DEPLOY_V5.5.md antes del deploy.
