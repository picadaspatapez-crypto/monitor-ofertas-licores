# Deploy v6.0.0.4 — Vinos La Reina terminal-404 hotfix

Aplicar sobre **v6.0.0.3**.

## Qué corrige
Cuando Vinos La Reina entraba en `playwright-fallback`, el navegador recibía correctamente HTTP 404 al pedir la página posterior a la última página real. El fallback trataba ese 404 como un fallo de recuperación, reintentaba tres veces y podía terminar marcando la categoría como fallida.

v6.0.0.4 devuelve inmediatamente ese 404 al loop de catálogo, que ya lo interpreta como fin normal de paginación cuando hubo páginas válidas previas.

## Deploy
1. Reemplazar los archivos del hotfix conservando sus rutas.
2. Commit/push a GitHub y desplegar en Railway.
3. No hay migraciones nuevas. Alembic continúa en `0013_watchlists`.
4. Ejecutar un `Run now`.

## Señal esperada
Al terminar una categoría debería aparecer, por ejemplo:

`Tienda de Vinos La Reina vinos: fin confirmado por HTTP 404 tras 20 páginas válidas.`

sin mensajes `fallback persistente agotado` ni la categoría marcada como fallida.
