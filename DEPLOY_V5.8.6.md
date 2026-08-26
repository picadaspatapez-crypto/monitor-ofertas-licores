# Deploy v5.8.6

## Objetivo

Corrige el fallo de arranque observado en v5.8.5:

`ModuleNotFoundError: No module named 'bs4'`

La causa no era que el collector necesitara una nueva dependencia del servicio de búsqueda. El nuevo `title_guard` importaba directamente `app.collectors.licor3b`; al resolver ese submódulo Python ejecutaba `app.collectors.__init__`, que importa collectors que requieren BeautifulSoup/Playwright. El servicio de búsqueda no debería cargar esos collectors para poder arrancar.

## Cambio

- Se creó `app/intelligence/licor3b_title_utils.py`, sin dependencias de scraping.
- `app/intelligence/title_guard.py` usa ahora ese módulo aislado.
- `app/collectors/licor3b.py` conserva los helpers privados como wrappers de compatibilidad, pero delega en el módulo aislado.
- Se mantiene toda la lógica de v5.8.5 de consistencia canonical/snapshot.
- No hay migración de base de datos.
- No se agregan dependencias al servicio de búsqueda.

## Validación

- `214 passed`
- `compileall`: OK
- Import del servicio de búsqueda con `bs4` y `playwright` bloqueados artificialmente: OK
- No se fuerza el import de `app.collectors.comercialjp` al cargar `app.search.service`.

## Deploy

1. Aplicar los archivos del hotfix sobre v5.8.5.
2. Commit/push.
3. Esperar que Build y Deploy terminen.
4. Confirmar `Network > Healthcheck = OK`.
5. Solo después hacer un `Run now`.

No cambiar el healthcheck ni aumentar el timeout para resolver este error: el problema era de importación durante el arranque.
