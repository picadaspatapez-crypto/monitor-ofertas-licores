# v6.0.0 — Watchlists Hotfix / Upgrade Package

Base requerida: **v5.9.2 — Expansion Consolidation**.

Este paquete incorpora la primera versión de la rama v6:

- `/vigilar PRODUCTO bajo PRECIO`
- `/vigilar PRODUCTO score N`
- `/vigilar PRODUCTO minimo`
- `/vigilar PRODUCTO cav MONTO`
- `/watchlist`
- `/quitarwatch ID`

## Importante

Esta versión **sí cambia el esquema**. Debe aplicarse `alembic upgrade head` y quedar en `0013_watchlists`.

No modifica collectors, Matching 2.0, Data Quality, scheduler ni la política híbrida de CAV.

Pruebas: **237 passed**.
