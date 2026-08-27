v5.9.0.2 — El Brindis WooCommerce Card Parser Hotfix

Base requerida: v5.9.0.1

Objetivo:
- Corregir El Brindis, que en v5.9.0.1 detectaba solo 1 tarjeta/producto por página.
- Interpretar correctamente el layout WooCommerce/Flatsome desde enlaces de producto, sin depender de h2/h3.
- Tratar HTTP 404 en páginas posteriores a una página válida como fin normal de paginación.
- Fallar de forma segura si el HTML expone muchos enlaces de productos pero el parser solo logra recuperar una fracción pequeña.

Aplicación:
1. Copiar el contenido de esta carpeta sobre la raíz del repositorio v5.9.0.1.
2. Reemplazar los archivos existentes.
3. Commit + push.
4. Esperar deployment verde en Railway.
5. Ejecutar un único Run now.

No hay migraciones nuevas.
La Koka y Rancho Wines no cambian.
