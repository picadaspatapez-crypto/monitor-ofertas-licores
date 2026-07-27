# Monitor de Ofertas de Licores v4.0

Plataforma modular de recolección e inteligencia de precios para tiendas chilenas.

## Estado de esta versión

**v4.0 — Multi-store Foundation** desacopla por completo los metadatos de cada tienda del pipeline. Licor3B continúa funcionando igual, pero una nueva tienda ya puede registrarse declarando su collector y agregándolo al registry, sin introducir condiciones en el runner.

```text
Collector registry
       ↓
Collect → Persist → Analyze → Report
       ↓
 PostgreSQL + Telegram
```

Esta entrega no modifica el esquema de PostgreSQL y no requiere variables nuevas en Railway.

## Ejecución

```bash
alembic upgrade head
python main.py
```

## Pruebas

```bash
pytest -q
```

## Próximo paso

La v4.1 incorporará el collector inicial de Líquidos.cl sobre esta base multi-tienda.

Consulta `docs/V4_ROADMAP.md` para la ruta completa hasta v5.0.
