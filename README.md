# Monitor de Ofertas de Licores

**Versión actual: v5.3.3 — Socomep Replacement.**

Plataforma chilena multi-tienda para recolectar precios, comparar productos equivalentes,
buscar desde web o Telegram y seguir favoritos con alertas personalizadas.

## Tiendas activas

- Licor3B
- Líquidos
- El Mundo del Vino
- Comercial JP
- Donde La Negra
- Distribuidora La Modelo
- Socomep

La Barra fue retirada del registry activo por no entregar un catálogo confiable desde Railway.
Su collector y datos históricos se conservan únicamente para diagnóstico; la tienda queda
marcada como inactiva y deja de participar en el buscador y comparador vigente.

## Novedades de v5.3.3

- Socomep reemplaza a La Barra con catálogo público Jumpseller.
- Recorre Licores, Vinos, Cervezas y Espumantes con paginación secuencial.
- Extrae precio actual, precio de referencia, disponibilidad y enlace canónico.
- Mantiene pausas breves entre páginas y el límite de 25 minutos por tienda.
- La sincronización de tiendas desactiva automáticamente collectors retirados.
- Los precios históricos de tiendas deshabilitadas se conservan, pero no aparecen como ofertas vigentes.
- El Mundo del Vino mantiene su revisión cada 12 horas y snapshot confiable.

## Arquitectura Railway

```text
Postgres
   ▲
   ├── monitor-ofertas-licores
   │      cron cada 6 horas
   │      7 collectors activos, máximo 4 workers
   │
   └── buscador-licores
          web /buscar + API + bot Telegram permanente
```

El Mundo del Vino se revisa cada 12 horas. Las demás tiendas activas se revisan en cada
ciclo de seis horas. Cada collector conserva un límite de 25 minutos.

## Despliegue

Consulta [`DEPLOY_V5.3.3.md`](DEPLOY_V5.3.3.md).

No hay migraciones nuevas. El head de Alembic continúa en `0007_telegram_favorites`.

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
