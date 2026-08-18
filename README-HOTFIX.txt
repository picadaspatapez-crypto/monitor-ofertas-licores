v5.8.3 — Canonical Pack Repair & Economic Sanity Guard

BASE REQUERIDA: v5.8.2 Pack Identity Guard

Aplicación:
1. Respalda PostgreSQL.
2. Copia TODO el contenido de esta carpeta sobre la raíz del repositorio v5.8.2.
3. Reemplaza archivos cuando se solicite.
4. Commit + push a Railway.
5. Después del deploy, ejecuta un único Run now.

No hay migraciones nuevas. Alembic sigue en 0012_commercial_intelligence.

Este hotfix corrige el caso en que un master histórico seguía mezclando un pack X6/X24 con una botella individual aun después de que v5.8.2 reconociera correctamente el título.
