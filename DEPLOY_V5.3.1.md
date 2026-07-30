# v5.3.1 — La Barra sitemap fallback y La Modelo completa

## Cambios

- La Barra deja de recorrer siete categorías vacías. Si la primera no expone productos, prueba `sitemap.xml` y extrae nombre/precio desde los datos estructurados de las fichas de producto.
- Si tampoco existe catálogo utilizable en sitemap, falla rápido y conserva el histórico.
- Distribuidora La Modelo detecta el total informado por el sitio (`Página 1 de 186`) y procesa las 186 páginas.
- El tope de seguridad interno queda en 220 páginas.

## Sin cambios

- No hay migraciones.
- No hay variables nuevas.
- Se mantiene el límite de 25 minutos por collector.
