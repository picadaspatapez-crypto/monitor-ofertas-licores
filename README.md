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
