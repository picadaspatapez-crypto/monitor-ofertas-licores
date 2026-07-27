# Despliegue v4.7 — Bot interactivo de Telegram

## 1. Actualizar el repositorio

Reemplaza el contenido del repositorio por esta versión y realiza el commit:

```text
Release v4.7 interactive Telegram search bot
```

La v4.7 incluye todo lo desarrollado hasta la v4.6. No debes instalar una
versión intermedia.

## 2. Servicio cron

El servicio `monitor-ofertas-licores` sigue usando:

```text
/railway.toml
```

No cambies su cron, comando de inicio ni política de reinicio.

## 3. Servicio `buscador-licores`

Mantén el servicio web existente conectado al mismo repositorio y usando:

```text
/railway.search.toml
```

No crees un tercer servicio. La web y el bot de Telegram se ejecutan juntos en
`buscador-licores`.

## 4. Variables obligatorias del buscador

En `buscador-licores → Variables`, confirma:

```env
DATABASE_URL=<referencia al PostgreSQL>
SEARCH_ACCESS_TOKEN=<tu clave privada>
TELEGRAM_BOT_TOKEN=<referencia o copia del token del scraper>
TELEGRAM_CHAT_ID=<referencia o copia del chat ID del scraper>
```

Railway permite crear referencias a variables de otro servicio del mismo
proyecto. Es preferible usar referencias para no duplicar secretos.

Para varios chats autorizados, agrega en su lugar:

```env
TELEGRAM_ALLOWED_CHAT_IDS=123456789,-1001234567890
```

Los IDs deben ser numéricos y estar separados por comas. Un grupo de Telegram
suele tener un ID negativo.

## 5. Variables opcionales

```env
TELEGRAM_SEARCH_BOT_ENABLED=true
TELEGRAM_SEARCH_RESULT_LIMIT=5
TELEGRAM_POLL_TIMEOUT_SECONDS=25
TELEGRAM_POLL_RETRY_SECONDS=5
SEARCH_MAX_AGE_HOURS=72
```

El límite de resultados admite entre 1 y 8 elementos para evitar mensajes
demasiado largos.

## 6. Desplegar

Al iniciar, el servicio ejecutará:

```text
alembic upgrade head
python -m app.search.reindex
python -m app.search.service
```

En los logs deberías ver algo similar a:

```text
BOT Telegram listo: @TuBot; chats autorizados=[...].
Servicio interactivo v4.7.0 · Interactive Telegram Search Bot · web=... · bot=activo.
```

Si aparece `bot=pendiente`, revisa `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID`.
El buscador web seguirá funcionando aunque el bot esté pendiente.

## 7. Probar desde Telegram

Abre el mismo bot que ya recibe las alertas y envía:

```text
/start
```

Luego prueba:

```text
/buscar johnnie black 750
```

También funciona sin comando:

```text
jack honey
```

El comando `/estado` informa cuántos productos unificados y publicaciones
vigentes existen en PostgreSQL.

## 8. Importante

No ejecutes dos servicios con long polling usando el mismo token. En esta
arquitectura solamente `buscador-licores` llama a `getUpdates`; el scraper cron
solo utiliza `sendMessage`, por lo que ambos pueden compartir el mismo bot.
