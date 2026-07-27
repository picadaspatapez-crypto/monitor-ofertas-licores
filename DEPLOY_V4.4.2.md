# Deploy v4.4.2

Esta corrección expone `__version__` desde `app/version.py`, que es requerido por
`app/pipeline/runner.py`. También reemplaza el `__init__.py` raíz inválido por un
módulo Python válido para que las pruebas puedan ejecutarse.

No contiene migraciones nuevas ni cambia las variables de Railway.

Commit sugerido:

    Release v4.4.2 version import fix
