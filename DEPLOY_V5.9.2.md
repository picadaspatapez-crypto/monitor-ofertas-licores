# Deploy v5.9.2 — Expansion Consolidation

## Base requerida

Aplicar sobre v5.9.1.2 funcional.

## Base de datos

No hay migraciones nuevas. No ejecutar una revisión manual de schema más allá del `alembic upgrade head` habitual del entrypoint.

## Variables opcionales

```env
EXPANSION_AUDIT_REPORT=true
EXPANSION_AUDIT_INTERVAL_HOURS=24
EXPANSION_AUDIT_RUNS_PER_STORE=3
```

Si no se agregan a Railway se usan esos valores por defecto.

## Verificación

1. Reemplazar los archivos del hotfix conservando rutas.
2. Commit/push a GitHub.
3. Esperar deployment verde en Railway.
4. No es necesario `Run now` sólo para activar la versión: el reporte usa ejecuciones ya persistidas.
5. En Telegram ejecutar `/auditoria`.
6. Si faltan ciclos, el resultado será `NOT_READY`; esto es esperado.
7. Tras 3 ejecuciones recientes por cada nueva tienda, revisar `STABLE/WATCH`.

La auditoría automática sólo se envía cuando las seis tiendas tienen la ventana mínima. Un resultado `STABLE` se deduplica para no repetir la confirmación indefinidamente.
