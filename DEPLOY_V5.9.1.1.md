# Deploy v5.9.1.1

1. Parte desde el repositorio actualmente en **v5.9.1**.
2. Descomprime este ZIP en la raíz del proyecto y permite reemplazar archivos.
3. Verifica que `app/version.py` indique `5.9.1.1`.
4. Haz commit y push a GitHub.
5. Espera que Railway termine el deployment en verde.
6. No hay migración de base de datos.
7. Ejecuta **Run now** una vez.

## Qué esperar en logs

### Licores.cl
Ya no debería verse `tarjetas=1, productos=1, global=1` en todas las categorías. Cada URL `/producto/detalle?id=N` conserva su identidad propia y las páginas siguientes usan `page=N&per-page=12`.

### Central Vinos y Licores
La categoría Espumantes debe consultar `/espumantes` en vez de `/espumante`; el HTTP 404 anterior debería desaparecer.

Si una tienda sigue fallando, conserva el guard de cobertura: no bajar `min_products` ni forzar persistencia de capturas parciales.
