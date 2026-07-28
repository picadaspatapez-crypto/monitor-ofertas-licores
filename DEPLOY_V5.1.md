# Despliegue v5.1 — Stability Hardening

Esta versión estabiliza Tost y limita la duración de cada collector sin separar GradoÚnico en otra región.

## Cambios

- Tost deja de depender de `products.json` y recorre las páginas HTML normales de sus colecciones.
- Tost descubre la cantidad real de páginas mediante paginación y el texto `Mostrando X de Y`.
- Hasta tres páginas de una misma colección Tost se descargan simultáneamente.
- Tost queda `BROKEN` si entrega menos de 50 productos; una captura parcial no se persiste.
- Todos los collectors tienen un presupuesto predeterminado de 25 minutos.
- GradoÚnico conserva preflight y circuit breaker en la misma región y servicio.
- Una ejecución con al menos una tienda correcta termina con código 0; Railway no marca todo el cron como `Crashed` por una tienda caída.
- Si todas las tiendas fallan, la ejecución sí termina con código 1.

## Variable opcional

```env
COLLECTOR_TIMEOUT_MINUTES=25
```

No es obligatorio agregarla: 25 minutos es el valor predeterminado.

## Despliegue

1. Reemplazar el repositorio con el contenido interior del ZIP.
2. Commit sugerido:

```text
Release v5.1 stability hardening
```

3. No crear servicios nuevos y no cambiar regiones.
4. Ejecutar manualmente el cron para validar.

## Logs esperados

```text
Ejecución paralela: workers=4; ... límite_por_tienda=25 min.
Tost whisky página 1: ...
Tost whisky página 2: ...
Resumen Tost: ... productos_únicos=...
```

Si GradoÚnico no conecta, debe fallar rápidamente mediante preflight/circuit breaker mientras las demás tiendas continúan.
