# v6.0.0.1 — Source Resilience Hotfix

Base requerida: **v6.0.0 — Watchlists**.

Este hotfix corrige fallos externos observados durante varios días sin cambiar el modelo de datos ni la lógica de watchlists.

## Cambios

- **CAV:** el listado usa la ruta raíz actual de la tienda; las fichas `/tienda/producto/...` se mantienen.
- **La Vinoteca:** HTTP 5xx persistente en una ventana VTEX se recupera dividiendo el rango de forma adaptativa.
- **Tienda de Vinos La Reina:** el fallback Chromium realiza hasta 3 intentos y conserva una sesión temporal para páginas siguientes.
- **La Modelo / La Vinoteca / CAV / Vinos La Reina / El Mundo del Vino:** si una fuente externa falla y existe un snapshot HEALTHY anterior, el ciclo queda `STALE` y reutiliza ese catálogo para comparaciones/watchlists.

## Seguridad de datos

Una captura parcial o fallida **no se persiste como catálogo sano**. El intento queda registrado y, cuando corresponde, se utiliza únicamente el último snapshot HEALTHY conocido.

## Base de datos

No hay migración nueva. Alembic continúa en `0013_watchlists`.

## Validación

- `python -m compileall -q app tests`: OK
- `pytest -q`: **241 passed**
