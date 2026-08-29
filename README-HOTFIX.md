# v5.9.1.2 — Vinos La Reina 202 Resilience

Hotfix de resiliencia para Tienda de Vinos La Reina cuando el storefront devuelve HTTP 202 o un HTML intermedio sin tarjetas de producto.

La ruta normal continúa siendo HTTP. El collector reintenta una vez con no-cache y solo si sigue sin catálogo activa Chromium/Playwright de manera lazy. Los guards existentes siguen cerrando la captura si tampoco se obtiene un catálogo confiable.
