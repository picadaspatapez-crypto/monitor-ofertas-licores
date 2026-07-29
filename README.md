# Monitor de Ofertas de Licores — v5.1.7

Plataforma chilena multi-tienda para recolectar precios, comparar productos equivalentes,
buscar desde web o Telegram y seguir favoritos con alertas personalizadas.

## Tiendas activas

- Licor3B
- Líquidos
- El Mundo del Vino
- Comercial JP

## Novedades de v5.1.7

- El Mundo del Vino respeta HTTP 429 con una pausa controlada de 30 a 120 segundos.
- Solo realiza un reintento tras el rate limit y no dispara HTML inmediatamente después.
- Conserva productos ya recopilados cuando una página posterior queda limitada.
- Una cobertura parcial suficiente se guarda como `DEGRADED`, no como fallo total.
- Se añaden pausas preventivas de 8 a 12 segundos entre categorías Shopify.
- El resumen multi-tienda se envía apenas terminan los collectors, antes del matching, la reindexación y los favoritos.
- Comercial JP continúa protegido contra inserciones concurrentes duplicadas.
- Cada collector mantiene un límite máximo de 25 minutos.

## Arquitectura Railway

```text
Postgres
   ▲
   ├── monitor-ofertas-licores
   │      cron cada 6 horas
   │      Licor3B + Líquidos + El Mundo del Vino + Comercial JP
   │
   └── buscador-licores
          web /buscar + API + bot Telegram permanente
```

Licor3B y Líquidos utilizan Playwright. El Mundo del Vino y Comercial JP utilizan HTTP directo.
No se crean servicios nuevos ni se modifican las regiones de Railway.

## Límite por tienda

El valor predeterminado es 25 minutos:

```env
COLLECTOR_TIMEOUT_MINUTES=25
```

La variable es opcional. El límite se verifica durante navegación, paginación,
scroll y solicitudes HTTP.

## Despliegue

Consulta [`DEPLOY_V5.1.7.md`](DEPLOY_V5.1.7.md).

No hay una migración nueva. El head de Alembic continúa en
`0007_telegram_favorites`.

## Ejecución local

```bash
pip install -r requirements.txt
alembic upgrade head
python main.py
```

Buscador web y bot:

```bash
pip install -r requirements-search.txt
./search_entrypoint.sh
```

## Pruebas

```bash
PYTHONPATH=. python -m pytest
```

## Tiendas activas en v5.1.3

Licor3B, Líquidos, El Mundo del Vino y Comercial JP. Tost y GradoÚnico permanecen deshabilitados para diagnóstico futuro.

## v5.2 — Siete tiendas

La operación activa incluye Licor3B, Líquidos, El Mundo del Vino, Comercial JP, La Barra, Donde La Negra y Distribuidora La Modelo. El pipeline mantiene cuatro workers máximos y 25 minutos de presupuesto por tienda. Las nuevas publicaciones se incorporan automáticamente al matching, buscador web, bot de Telegram y favoritos.
