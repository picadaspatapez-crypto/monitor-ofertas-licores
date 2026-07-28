# Deploy v5.1.8

Hotfix para conservar y persistir capturas parciales confiables de El Mundo del Vino.

## Cambios

- Una captura con catálogo absoluto plausible y secciones útiles queda `DEGRADED`, no `BROKEN`.
- Las secciones parciales por HTTP 429 reciben una penalización menor que una sección totalmente fallida.
- Una caída histórica de cobertura no convierte automáticamente una captura ya validada como `DEGRADED` en `BROKEN`.
- Se mantienen el último catálogo confiable y la protección contra capturas con menos de 120 productos.

## Archivos del hotfix

- `app/collectors/elmundodelvino.py`
- `app/pipeline/runner.py`
- `app/version.py`
