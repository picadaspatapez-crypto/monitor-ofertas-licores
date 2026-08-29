# Deploy v5.9.1
1. Partir de v5.9.0.2 estable.
2. Copiar el contenido del ZIP sobre la raíz del repositorio, respetando rutas.
3. Commit y push a GitHub.
4. Esperar Build / Deploy / Healthcheck verdes en Railway.
5. Ejecutar un solo Run now.
6. Revisar individualmente Licores.cl, Central Vinos y Licores y Tienda de Vinos La Reina.
7. Si una fuente falla o entrega cobertura baja, no rebajar los guards: conservar el catálogo histórico y diagnosticar esa fuente.

Diseño:
- Licores.cl: categorías públicas /producto/listado?categoria_id=..., paginación page/per-page; parser específico para no confundir precios tachados inconsistentes con precio vigente.
- Central: Jumpseller HTTP, categorías públicas y paginación ?page=N; parser tolerante a productos publicados en rutas raíz.
- Vinos La Reina: WooCommerce HTTP, categorías públicas, /page/N/, parser WooCommerce robusto reutilizado de v5.9.0.2.
