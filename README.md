# Monitor de Ofertas de Licores — v4.6.0

Plataforma multi-tienda para **Licor3B** y **Líquidos.cl**. Recolecta los
catálogos en paralelo, conserva historial en PostgreSQL, compara productos
equivalentes y ahora ofrece un **buscador privado desde el navegador**.

## Novedades de v4.6

- Catálogo unificado enriquecido con marca, variante, volumen, cantidad y alias.
- Motor de búsqueda tolerante a nombres incompletos y errores comunes.
- Reconoce consultas como `jw black 750`, `etiqueta negra` o `jack honey`.
- Agrupa las publicaciones equivalentes de ambas tiendas.
- Muestra el mejor precio, ahorro, enlaces y fecha de actualización.
- Página web privada protegida mediante `SEARCH_ACCESS_TOKEN`.
- Endpoint JSON `/api/search` preparado para ser reutilizado por el bot v4.7.
- CLI técnico: `python -m app.search.cli "johnnie black 750"`.
- Migración Alembic `0005_search_catalog`.

## Arquitectura de despliegue

La misma base de código se usa en **dos servicios Railway**:

```text
Servicio 1 · Scraper cron
Cada 6 horas
Licor3B + Líquidos → PostgreSQL

Servicio 2 · Buscador web
Siempre activo
Navegador → PostgreSQL
```

El servicio cron conserva `railway.toml`. El nuevo servicio web utiliza
`railway.search.toml` y `search_entrypoint.sh`.

## Variables del servicio web

```env
DATABASE_URL=<referencia al mismo PostgreSQL>
SEARCH_ACCESS_TOKEN=<clave privada larga>
SEARCH_RESULT_LIMIT=8
SEARCH_MAX_AGE_HOURS=72
```

Las dos últimas son opcionales. El buscador no abre las tiendas al consultar;
lee los precios ya registrados en PostgreSQL.

## Despliegue

Consulta [`DEPLOY_V4.6.md`](DEPLOY_V4.6.md).
