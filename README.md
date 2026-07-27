
## v4.4 — Performance Engine

La recolección de Licor3B y Líquidos se ejecuta en paralelo, con bloqueo de recursos visuales, esperas adaptativas y métricas por fase. Consulta `DEPLOY_V4.4.md`.

# Monitor de Ofertas de Licores — v4.3.0

Plataforma multi-tienda que recolecta los catálogos de **Licor3B** y
**Líquidos.cl**, conserva el historial de precios en PostgreSQL y envía alertas
inteligentes por Telegram.

## Qué cambia en v4.3

La aplicación continúa ejecutándose una sola vez y terminando, pero ahora el
archivo `railway.toml` programa Railway para iniciarla automáticamente cada seis
horas:

```cron
0 */6 * * *
```

Los horarios de Railway se evalúan en UTC. El proceso sigue esta secuencia:

```text
Railway Cron
    ↓
Licor3B
    ↓
Líquidos
    ↓
PostgreSQL
    ↓
Política inteligente de alertas
    ↓
Telegram solo cuando corresponde
    ↓
El proceso termina
```

## Política inteligente de Telegram

### Bajas relevantes

Se envía una alerta inmediata cuando la baja real cumple al menos una condición:

- baja igual o superior al **5 %**; o
- ahorro igual o superior a **$1.000 CLP**.

Estos valores se pueden ajustar con variables de entorno.

### Ranking de mejores precios

Se mantienen las reglas de v4.2:

- hasta **30 productos por tienda**;
- sin techo máximo de precio;
- prioridad para bajas históricas y descuentos informados;
- tres mensajes de diez productos.

El ranking se envía cuando:

1. todavía no existe un ranking previo de esa tienda;
2. cambió algún producto, precio o posición del top 30; o
3. han pasado 24 horas desde el último ranking, aunque siga idéntico.

### Ejecuciones silenciosas

Cuando el collector está sano, no existen bajas relevantes y el ranking no
cambió ni requiere refresco, la ejecución queda guardada en PostgreSQL pero no
manda Telegram.

### Incidencias

El sistema avisa cuando:

- una tienda queda `DEGRADED` o `BROKEN`;
- falla una categoría;
- se detecta un posible cambio estructural;
- el collector vuelve a estar `HEALTHY`;
- el collector lanza una excepción completa.

La misma incidencia no se repite continuamente. Los recordatorios idénticos se
limitan a uno cada 24 horas.

## Deduplicación persistente

La tabla `alerts` ahora guarda:

- tienda;
- ejecución;
- tipo de alerta;
- huella del contenido;
- clave única de deduplicación;
- estado `pending`, `sent` o `failed`;
- fecha de envío o error.

Esto evita que un reinicio o una ejecución repetida envíen el mismo mensaje dos
veces. Los avisos fallidos quedan disponibles para reintento.

## Variables nuevas opcionales

```env
ALERT_MIN_DROP_PERCENT=5
ALERT_MIN_DROP_CLP=1000
TELEGRAM_DIGEST_INTERVAL_HOURS=24
TELEGRAM_REPORT_LIMIT=30
TELEGRAM_CHANGE_LIMIT=10
ALERT_NEW_PRODUCTS=false
ALERT_PRICE_INCREASES=false
```

No es obligatorio agregarlas en Railway: esos son los valores predeterminados.

## Base de datos

Alembic aplica automáticamente:

```text
0004_smart_alerts
```

La migración conserva todo el historial existente y amplía la tabla `alerts`
para soportar eventos de tienda y de ejecución.

## Despliegue

Consulta `DEPLOY_V4.3.md`.
