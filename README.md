# Monitor de Ofertas de Licores — v5.1.0

Plataforma chilena multi-tienda para recolectar precios, comparar productos equivalentes,
buscar desde web o Telegram y seguir favoritos con alertas personalizadas.

## Tiendas activas

- Licor3B
- Líquidos
- Tost
- GradoÚnico

## Novedades de v5.1

- Tost recorre las páginas HTML normales de sus colecciones.
- La paginación se descubre automáticamente y se descargan hasta tres páginas Tost a la vez.
- Un resultado Tost inferior a 50 productos se considera incompleto y queda `BROKEN`.
- Las capturas `BROKEN` no se guardan, por lo que se conserva el último catálogo confiable.
- Cada collector dispone de un máximo predeterminado de 25 minutos.
- GradoÚnico permanece en el mismo servicio y región, con preflight y circuit breaker.
- Railway solo marca el cron como fallido cuando ninguna tienda finaliza correctamente.
- Matching, buscador, Telegram y favoritos continúan usando únicamente ejecuciones confiables.

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

Licor3B y Líquidos utilizan Playwright. Tost y GradoÚnico utilizan HTTP directo.
No se crea un servicio nuevo ni se cambia GradoÚnico de región.

## Límite por tienda

El valor predeterminado es 25 minutos:

```env
COLLECTOR_TIMEOUT_MINUTES=25
```

La variable es opcional. El límite se verifica durante navegación, paginación,
scroll y solicitudes HTTP.

## Despliegue

Consulta [`DEPLOY_V5.1.md`](DEPLOY_V5.1.md).

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
