# v6.0.0.4 — Browser Terminal 404 Recovery

Hotfix de Vinos La Reina para hacer coherente el final de paginación entre HTTP y Chromium.

- Un HTTP 404 real devuelto por Playwright ahora se propaga como `HtmlFetchResult(404, ...)`.
- El loop común lo trata como fin normal cuando ya existían páginas válidas.
- Se evita el ciclo innecesario Chromium -> RuntimeError -> HTTP 202 -> Chromium.
- No cambia el parser de productos, el guard de agotados, CAV, matching, watchlists ni PostgreSQL.
- Sin migraciones nuevas.
