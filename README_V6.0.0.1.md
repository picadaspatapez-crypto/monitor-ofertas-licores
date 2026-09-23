# v6.0.0.1 — Source Resilience Hotfix

Hotfix de resiliencia para cuatro fuentes externas observadas inestables en septiembre de 2026.

- **CAV:** mueve el listado InstantSearch desde `/tienda` a la ruta raíz actual, manteniendo producto URLs `/tienda/producto/...`.
- **La Vinoteca:** los HTTP 5xx de VTEX en ventanas de 50 se recuperan dividiendo adaptativamente el rango antes de rendirse.
- **Tienda de Vinos La Reina:** Chromium hace hasta 3 intentos y mantiene una ventana de navegación persistente después de una respuesta 202/interstitial.
- **La Modelo / La Vinoteca / CAV / Vinos La Reina / El Mundo del Vino:** si la fuente externa falla y existe un snapshot HEALTHY anterior, el ciclo queda **STALE** y reutiliza ese catálogo para no interrumpir comparaciones ni watchlists.

No hay migraciones de base de datos ni variables nuevas.
