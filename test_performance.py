# Migración a v2.0

Esta versión no modifica el esquema de PostgreSQL y no requiere una migración Alembic nueva.

## Despliegue

1. Reemplazar el repositorio por el contenido de este paquete.
2. Conservar las variables de Railway.
3. Hacer un único commit.
4. Usar **Deploy Latest Commit**.
5. Confirmar `Pipeline licor3b completado`.

## Rollback

En Railway se puede volver al deployment anterior. La base de datos es compatible porque v2 reutiliza las tablas existentes.
