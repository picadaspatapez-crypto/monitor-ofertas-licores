# Monitor de Ofertas de Licores v2.0

Plataforma modular de recolección e inteligencia de precios para tiendas chilenas.

## Arquitectura

```text
Collector -> Pipeline -> Matching -> PostgreSQL -> Analyzer -> Report -> Telegram
```

## Ejecución

```bash
alembic upgrade head
python main.py
```

## Pruebas

```bash
pytest -q
```

Consulta `docs/V2_ARCHITECTURE.md` y `docs/MIGRATION_V2.md`.

## Cobertura Licor3B

Desde v2.2, Licor3B se recopila por categorías raíz y no solo desde la página de ofertas. Consulta `docs/LICOR3B_FULL_CATALOG.md` para modos de ejecución y diagnóstico.

## Estado de Licor3B

El collector de Licor3B está cerrado en v3.0 y siempre recorre el catálogo completo. Descubre automáticamente las categorías, continúa ante fallos aislados y persiste métricas de salud por ejecución. No necesita `LICOR3B_CATALOG_MODE`. Consulta `docs/LICOR3B_FINAL.md`.
