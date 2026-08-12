v5.5.3 — Search UI Refresh

BASE REQUERIDA
v5.5.2 — Pagination Boundary & CAV Sharded Catalog Hotfix

QUÉ HACE
Actualiza la interfaz web del buscador/comparador. No modifica collectors,
matching, scheduler, Telegram ni base de datos.

APLICACIÓN
1. Copia TODO el contenido interior de esta carpeta sobre la raíz de v5.5.2.
2. Reemplaza los archivos existentes respetando las rutas.
3. Commit + push.
4. Espera el deployment de Railway.
5. Abre /buscar y usa Ctrl+F5 si el navegador conserva el CSS anterior.

NO REQUIERE
- Run now del collector.
- Variables nuevas.
- Migración Alembic.

ALEMBIC
Debe seguir en 0009_price_contexts.

ROLLBACK
Restaura app/search/web.py, app/search/static/search.css y app/version.py desde v5.5.2.
No hay rollback de base de datos.
