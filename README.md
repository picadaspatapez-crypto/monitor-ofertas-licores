# Monitor de Ofertas de Licores — v5.0.0

Plataforma chilena multi-tienda para recolectar precios, comparar productos equivalentes,
buscar desde web o Telegram y seguir favoritos con alertas personalizadas.

## Tiendas activas

- Licor3B
- Líquidos
- Tost
- GradoÚnico

## Novedades de v5.0

- Dos collectors nuevos: `TostCollector` y `GradoUnicoCollector`.
- Cuatro tiendas ejecutándose en paralelo con un máximo seguro de cuatro workers.
- Tost y GradoÚnico usan solicitudes HTTP directas; Licor3B y Líquidos conservan Playwright.
- Matching corregido para asociar el mismo producto en tres o cuatro tiendas, no solo en un par.
- Comparador y buscador muestran todas las ofertas disponibles por tienda.
- Botones de Telegram organizados en filas de dos, con hasta cuatro tiendas por resultado.
- Filtros adicionales para evitar mezclar botellas con packs, regalos o productos personalizados.
- Resumen compacto obligatorio al terminar cada revisión, con el estado de todas las tiendas.
- `/estado` informa la última ejecución, salud y cantidad de productos de cada collector.
- Favoritos y precios objetivo funcionan sobre el catálogo conjunto de las cuatro tiendas.

## Arquitectura Railway

```text
Postgres
   ▲
   ├── monitor-ofertas-licores
   │      cron cada 6 horas
   │      Licor3B + Líquidos + Tost + GradoÚnico
   │
   └── buscador-licores
          web /buscar + API + bot Telegram permanente
```

Los collectors se ejecutan simultáneamente, pero únicamente Licor3B y Líquidos abren
Chromium. Tost y GradoÚnico consultan catálogos HTTP, reduciendo el consumo de memoria.

## Despliegue

Consulta [`DEPLOY_V5.0.md`](DEPLOY_V5.0.md).

No hay una migración nueva en esta versión. El head de Alembic continúa en
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
