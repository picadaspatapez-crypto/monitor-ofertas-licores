# v6.0.0.2 — CAV Route Recovery

Hotfix focalizado para CAV después de detectar que v6.0.0.1 apuntaba el estado InstantSearch a la portada `/`.

La portada de CAV devuelve HTTP 200 y contiene productos editoriales, por lo que parecía parseable, pero ignora `fR[...]`, `p` e `idx`. El síntoma era exactamente el observado en Railway: 11 productos idénticos en cada shard y `p=0`/`p=1` aparentemente alias.

Cambios:
- `SHOP_URL` vuelve a `https://cav.cl/tienda`.
- Se valida la URL efectiva tras cada `page.goto`.
- Se rechaza una redirección silenciosa a `/` o la pérdida de filtros.
- Se detectan tres primeras páginas idénticas y pequeñas entre shards como señal de filtro inefectivo.
- Se mantiene STALE recovery sin modificar snapshots históricos.

No hay migraciones ni nuevas variables de entorno.
