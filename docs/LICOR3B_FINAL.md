# Licor3B collector final (v3.0)

Licor3B queda cerrado como primer collector de referencia para la plataforma multi-tienda.

## Comportamiento

1. Abre la portada de Licor3B y descubre automáticamente categorías raíz desde el menú.
2. Si el menú no puede leerse, usa una lista de respaldo conocida.
3. Recorre cada categoría con paginación `?product-page=N`.
4. Una categoría fallida no detiene las demás.
5. Deduplica globalmente por URL y conserva todas las categorías de origen en memoria.
6. Registra métricas por categoría y globales.
7. Detecta HTTP 200 con cero tarjetas como posible cambio estructural.
8. Calcula salud `HEALTHY`, `DEGRADED` o `BROKEN`.
9. Compara el total con la ejecución exitosa anterior para detectar caídas anormales.

## Persistencia

La migración `0003_scrape_run_observability` agrega a `scrape_runs`:

- categorías descubiertas, visitadas, correctas y fallidas;
- páginas y tarjetas;
- duplicados eliminados;
- alertas estructurales;
- estado y puntaje de salud;
- `metrics_json` con el detalle por categoría.

## Configuración

No se requiere `LICOR3B_CATALOG_MODE`. El collector siempre revisa el catálogo completo.

## Criterios de salud

- `HEALTHY`: todas las categorías correctas, sin alertas estructurales.
- `DEGRADED`: fallos aislados, alertas estructurales o caída relevante frente al total anterior.
- `BROKEN`: no hay productos, fallan varias categorías o el catálogo cae a menos de 40% del total anterior.
