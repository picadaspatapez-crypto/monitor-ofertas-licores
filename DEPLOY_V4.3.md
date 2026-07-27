# Despliegue v4.3 — Smart Alerts & Railway Cron

## 1. Reemplazar el repositorio

Copia el contenido interior de este ZIP sobre el repositorio actual y conserva
las variables secretas únicamente en Railway.

Commit sugerido:

```text
Release v4.3 smart alerts and Railway cron
```

## 2. Desplegar

Railway detectará el `Dockerfile` y ejecutará al iniciar:

```sh
alembic upgrade head
python main.py
```

Alembic aplicará `0004_smart_alerts` antes de comenzar el scraping.

## 3. Periodicidad incluida

`railway.toml` define:

```toml
[deploy]
startCommand = "/app/entrypoint.sh"
restartPolicyType = "NEVER"
cronSchedule = "0 */6 * * *"
```

Esto ejecuta el monitor a las 00:00, 06:00, 12:00 y 18:00 UTC. Railway puede
mostrar los cambios de configuración como cambios pendientes; revísalos y
confírmalos al desplegar.

El programa debe terminar al completar ambas tiendas. Si una ejecución sigue
activa al llegar la siguiente hora programada, Railway omitirá esa nueva
instancia en vez de superponer dos scrapers.

## 4. Variables

No se agregan variables obligatorias. Puedes mantener solo las actuales.

Valores predeterminados de v4.3:

```env
ALERT_MIN_DROP_PERCENT=5
ALERT_MIN_DROP_CLP=1000
TELEGRAM_DIGEST_INTERVAL_HOURS=24
TELEGRAM_REPORT_LIMIT=30
TELEGRAM_CHANGE_LIMIT=10
ALERT_NEW_PRODUCTS=false
ALERT_PRICE_INCREASES=false
```

Para recibir también productos nuevos o alzas:

```env
ALERT_NEW_PRODUCTS=true
ALERT_PRICE_INCREASES=true
```

No se recomienda habilitarlas todavía, porque pueden generar bastante ruido.

## 5. Qué revisar en los logs

Al iniciar:

```text
Monitor de Licores v4.3.0 · Smart Alerts & Railway Cron
Alertas inteligentes: baja ≥ 5.0% o ≥ $1.000; digest cada 24 h.
```

Después de cada tienda aparecerá una de estas salidas:

```text
Telegram Licor3B: bundles enviados=..., omitidos=..., fallidos=...
```

O, cuando no haya novedades:

```text
Telegram Licor3B: sin cambios relevantes; 0 mensajes.
```

## 6. Primer comportamiento esperado

Como la base todavía no tiene registros `ranking_digest` de v4.3, la primera
ejecución enviará el resumen inteligente y los 30 mejores precios de cada
tienda. Las siguientes ejecuciones quedarán silenciosas si nada cambia, salvo
el refresco periódico configurado cada 24 horas.
