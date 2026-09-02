# Deploy v6.0.0 — Watchlists

## Base

Aplicar sobre **v5.9.2 — Expansion Consolidation**.

## Cambios de esquema

Esta versión sí incorpora una migración:

```text
0013_watchlists
```

Railway debe ejecutar el flujo habitual de Alembic. Si el deploy no lo hace automáticamente, ejecutar:

```bash
alembic upgrade head
```

Después verificar:

```bash
alembic current
```

Debe mostrar `0013_watchlists (head)`.

## Variables Railway

No se agregan variables obligatorias. Se reutilizan Telegram, PostgreSQL, CAV y los límites de favoritos existentes.

## Verificación rápida

1. Esperar deploy verde.
2. No es necesario forzar un scraping para probar la interfaz.
3. En Telegram ejecutar `/watchlist`.
4. Crear una regla que no esté cumplida, por ejemplo `/vigilar PRODUCTO score 99`.
5. Confirmar que aparece en `/watchlist`.
6. Probar además una regla de precio objetivo.
7. En el siguiente ciclo completo HEALTHY, la evaluación de favoritos/watchlists corre automáticamente.

## Rollback

El código v5.9.2 no conoce las columnas nuevas, pero las columnas son aditivas. Para rollback de código no es necesario bajar inmediatamente la migración. Si se requiere rollback completo de esquema:

```bash
alembic downgrade 0012_commercial_intelligence
```

Esto elimina únicamente las cuatro columnas de watchlists.
