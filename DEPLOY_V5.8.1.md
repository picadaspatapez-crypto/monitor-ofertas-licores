# Deploy v5.8.1 — Commercial Radar Visibility Hotfix

Base requerida: **v5.8.0**.

## Qué corrige

En v5.8.0 los comandos `/radar` y `/minimos` podían responder correctamente pero sin filas cuando el mercado no cumplía simultáneamente los umbrales estrictos de señal comercial.

La v5.8.1 separa dos conceptos:

- **Alertas automáticas:** conservan los filtros estrictos de v5.8.0.
- **Consultas interactivas:** muestran primero señales estrictas y, si no existen, degradan de forma segura a las mejores oportunidades verificadas o a los productos más cercanos a su mínimo histórico.

No se modifican collectors, matching, Data Quality, scheduler, CAV ni persistencia.

## Despliegue

1. Haz un respaldo normal del repositorio. No hay migración de base de datos.
2. Copia el contenido interior del hotfix sobre la raíz de la v5.8.0 y reemplaza archivos.
3. Commit + push.
4. Espera a que Railway termine el deployment.
5. Prueba `/radar` y `/minimos`.

No hace falta `Run now`: ambos comandos consultan los `opportunity_snapshots` e históricos ya persistidos.

## Resultado esperado

Si existen señales excepcionales, `/radar` mantiene el título de señales verificadas. Si no las hay, mostrará `Radar comercial · mejores oportunidades actuales`.

Si no hay productos dentro del umbral estricto de mínimo histórico, `/minimos` mostrará `Precios más cercanos a su mínimo histórico`, incluyendo el mínimo y la distancia porcentual.
