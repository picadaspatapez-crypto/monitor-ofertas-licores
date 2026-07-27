# Deploy v4.4.3 — Playwright Wait Fix

Corrige el fallo observado en Railway:

```text
TypeError: Page.wait_for_function() takes 2 positional arguments but 3 positional arguments ... were given
```

En la API Python de Playwright, `arg` es un parámetro keyword-only. La v4.4.2 lo enviaba como segundo argumento posicional en dos helpers de rendimiento.

## Archivos modificados

- `app/performance.py`
- `app/version.py`
- `tests/test_performance.py`

## Base de datos

No incluye migraciones. No es necesario revertir `0004_smart_alerts` ni borrar PostgreSQL.

## Railway

No cambia `railway.toml`, el cron ni las variables. Después del commit puede ejecutarse manualmente con **Run now** para verificar el collector.
