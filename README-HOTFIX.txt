HOTFIX v5.3.4 — EL MUNDO STOREFRONT API HARDENING

Aplicar solamente sobre v5.3.3 Socomep Replacement.
Copiar el contenido interior de esta carpeta sobre la raíz del repositorio,
respetando exactamente las rutas y reemplazando los archivos existentes.

Este hotfix cambia la fuente principal de El Mundo del Vino desde products.json
a Shopify Storefront GraphQL, añade espera inicial aleatoria y manejo conservador
de HTTP 429/430/403. Mantiene el último snapshot HEALTHY si la tienda bloquea.

No borrar PostgreSQL y no ejecutar migraciones manuales.
No ejecutar varios Run now consecutivos después del despliegue.
