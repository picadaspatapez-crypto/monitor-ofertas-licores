# v5.9.0.1 — HTTP Catalog PhaseMetrics hotfix

Corrige el fallo de El Brindis y Rancho Wines:
`AttributeError: 'PhaseMetrics' object has no attribute 'download'`.

Causa: el helper HTTP nuevo de v5.9.0 trataba `PhaseMetrics` como si tuviera atributos `.download` y `.parse`. La API real usa `metrics.add(nombre, ms)`.

Cambios:
- `metrics.download += ...` -> `metrics.add('download', ...)`
- `metrics.parse += ...` -> `metrics.add('parse', ...)`
- Sin cambios de DB, matching, scheduler o collectors existentes.

Despliegue: copiar el contenido del ZIP sobre v5.9.0, commit/push, esperar deploy verde y hacer un Run now.
