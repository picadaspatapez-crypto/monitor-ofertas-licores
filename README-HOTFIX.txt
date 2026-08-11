v5.5.2 — PAGINATION BOUNDARY & CAV SHARDED CATALOG HOTFIX
==========================================================

BASE OBLIGATORIA: v5.5.1.

Corrige:
- La Vinoteca: la cola repetida posterior al catálogo VTEX pasa a ser una señal terminal segura.
- La Vinoteca: se leen también REST-Content-Range / X-VTEX-Content-Range.
- CAV: deja de consultar el índice global cercano al límite de ~1000 resultados.
- CAV: se divide por familias y por tipos de vino para obtener cobertura completa por shards.
- CAV: una cola editorial repetida al final de cada shard se interpreta como fin natural, no como fallo.

CAV SIGUE EN DIAGNÓSTICO y NO modifica el comparador público.
NO HAY MIGRACIONES NUEVAS. Alembic permanece en 0009_price_contexts.

Aplicación:
1. Copia el CONTENIDO de este hotfix sobre la raíz de v5.5.1.
2. Reemplaza archivos.
3. Commit + push.
4. Espera deploy exitoso en Railway.
5. Ejecuta un único Run now de validación.

Lee DEPLOY_V5.5.2.md antes del deploy.
