HOTFIX v5.8.4 — Licor3B Title Integrity Guard

BASE REQUERIDA
v5.8.3 — Canonical Pack Repair & Economic Sanity Guard

APLICACIÓN
1. Respaldar PostgreSQL.
2. Copiar el contenido del ZIP hotfix sobre la raíz del repositorio v5.8.3.
3. Reemplazar los archivos conservando las rutas.
4. Commit + push.
5. Confirmar deployment exitoso. No hay migraciones nuevas; Alembic sigue en 0012_commercial_intelligence.
6. Ejecutar un único Run now para reparar nombres Licor3B persistidos y recalcular snapshots.

QUÉ CORRIGE
- Títulos de tarjetas Licor3B contaminados con texto de productos vecinos.
- Usa el slug estable de la URL solo cuando existe evidencia fuerte de contaminación.
- Repara filas históricas de Licor3B sin borrar PriceObservations.
- Reconstruye nombres canónicos afectados.
- Purga snapshots derivados para recalcular radar/minimos.
- Añade un guard vivo en /radar y /minimos mientras sobreviva un snapshot viejo.

Consulta DEPLOY_V5.8.4.md antes de desplegar.
