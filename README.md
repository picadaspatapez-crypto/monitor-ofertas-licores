# Monitor de ofertas de licores — v2

Esta versión:

- separa configuración, scraper, base de datos y Telegram;
- guarda productos en PostgreSQL;
- registra una observación de precio en cada ejecución;
- distingue productos nuevos y bajas de precio;
- evita tratar cada ejecución como si fuera una oferta nueva.

## Estructura

```text
app/
├── config.py
├── database.py
├── models.py
├── repository.py
├── runner.py
├── scrapers/
│   └── licor3b.py
└── services/
    └── telegram.py
```

## Variables requeridas

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `DATABASE_URL`
- `MAX_PRODUCT_PRICE`
- `TOTAL_BUDGET`
- `MAX_UNITS_PER_PRODUCT`
- `MIN_TARGET_MARGIN`
- `DELIVERY_COMMUNE`

## Migraciones y seguimiento operativo

Esta versión incorpora Alembic y agrega:

- `stores`: registro de tiendas;
- `scrape_runs`: resultado de cada ejecución;
- `alerts`: prevención de avisos duplicados;
- `products.store_id`: transición hacia múltiples tiendas;
- `price_observations.scrape_run_id`: trazabilidad de observaciones.

El contenedor ejecuta automáticamente:

```bash
alembic upgrade head
python main.py
```

La primera migración es defensiva y conserva las tablas y datos creados por la versión anterior.
