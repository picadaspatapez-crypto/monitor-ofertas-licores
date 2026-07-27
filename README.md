# Monitor de Ofertas de Licores — v4.7.0

Plataforma multi-tienda para **Licor3B** y **Líquidos.cl**. Recolecta los
catálogos en paralelo, conserva historial en PostgreSQL, compara productos
equivalentes y permite consultar el último precio desde la web o directamente
en Telegram.

## Novedades de v4.7

- Bot interactivo de Telegram conectado al catálogo unificado.
- Búsqueda mediante `/buscar johnnie black 750` o escribiendo el producto sin comando.
- Respuestas con mejor precio, ahorro, tienda, confianza y botones de compra.
- Comandos `/buscar`, `/estado` y `/ayuda` registrados automáticamente.
- Acceso privado por `TELEGRAM_CHAT_ID` o `TELEGRAM_ALLOWED_CHAT_IDS`.
- Long polling integrado al servicio `buscador-licores`; no requiere webhook.
- Offset de Telegram persistido en PostgreSQL para evitar responder dos veces tras reinicios.
- Migración Alembic `0006_telegram_bot_state`.
- El buscador web privado de la v4.6 continúa disponible.

## Arquitectura de despliegue

La misma base de código sigue usando solamente **dos servicios Railway**:

```text
Servicio 1 · Scraper cron
Cada 6 horas
Licor3B + Líquidos → PostgreSQL

Servicio 2 · Buscador interactivo
Siempre activo
Web + Telegram → PostgreSQL
```

No debes crear un tercer servicio para el bot. La v4.7 amplía el servicio
`buscador-licores` existente.

## Variables del servicio `buscador-licores`

```env
DATABASE_URL=<referencia al mismo PostgreSQL>
SEARCH_ACCESS_TOKEN=<clave privada larga>
TELEGRAM_BOT_TOKEN=<el mismo token usado por el scraper>
TELEGRAM_CHAT_ID=<el mismo chat autorizado usado por el scraper>
```

Opcionalmente, para autorizar varios chats:

```env
TELEGRAM_ALLOWED_CHAT_IDS=123456789,-1001234567890
```

Cuando `TELEGRAM_ALLOWED_CHAT_IDS` está presente reemplaza el valor individual
de `TELEGRAM_CHAT_ID` para el bot interactivo.

## Uso en Telegram

```text
/start
/buscar johnnie black 750
/estado
```

También puedes escribir directamente:

```text
jack honey
```

El bot consulta PostgreSQL y no abre las tiendas al recibir cada mensaje.

## Despliegue

Consulta [`DEPLOY_V4.7.md`](DEPLOY_V4.7.md).
