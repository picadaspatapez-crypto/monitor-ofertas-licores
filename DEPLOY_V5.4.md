# Despliegue v5.4.0 — Catalog Intelligence & Reliability

## Base requerida

Este paquete está diseñado para actualizar directamente:

```text
v5.3.4 — El Mundo Storefront API Hardening
```

No lo apliques sobre una versión anterior sin pasar primero por v5.3.4.

## Opción A: ZIP completo

1. Respaldar el repositorio y la base PostgreSQL de Railway.
2. Reemplazar el contenido del repositorio por el ZIP completo de v5.4.
3. Conservar en Railway las variables sensibles existentes.
4. Hacer commit y push.
5. Verificar que el deploy ejecute `alembic upgrade head` sin errores.

## Opción B: hotfix ZIP

1. Descomprimir `v5.4-catalog-intelligence-reliability-hotfix.zip`.
2. Copiar **el contenido interior de la carpeta raíz del hotfix** sobre la raíz
   de la v5.3.4.
3. Reemplazar los archivos existentes y conservar las rutas.
4. Hacer commit y push a GitHub.
5. Railway ejecutará la migración antes de iniciar el pipeline.

## Migración de base de datos

La migración nueva es:

```text
0008_catalog_intelligence
```

Añade a `products`:

```text
sku
ean
is_available
missing_streak
last_available_at
unavailable_since
reactivated_at
last_confirmed_run_id
```

También crea:

```text
matching_rules
master_price_statistics
opportunity_snapshots
```

No borra productos, observaciones, favoritos ni alertas anteriores. Los
productos existentes se inicializan como disponibles y su última disponibilidad
se obtiene de `last_seen_at` o `first_seen_at`.

## Variables recomendadas

Las variables existentes continúan siendo compatibles. Añade o revisa:

```text
APP_TIMEZONE=America/Santiago
SCHEDULER_GRACE_MINUTES=15
AVAILABILITY_MISSING_THRESHOLD=2
TELEGRAM_COMPARISON_LIMIT=30
SEARCH_RESULT_LIMIT=30
OPPORTUNITY_REPORT_LIMIT=20
WEEKLY_HEALTH_REPORT=true
WEEKLY_HEALTH_INTERVAL_HOURS=168
FAVORITE_MIN_DROP_CLP=10
```

Mantén:

```text
COLLECTOR_WORKERS=4
COLLECTOR_TIMEOUT_MINUTES=25
EL_MUNDO_INTERVAL_HOURS=12
```

`EL_MUNDO_STOREFRONT_ACCESS_TOKEN` continúa siendo opcional.

## Primera ejecución

La primera ejecución posterior al deploy puede tardar un poco más al:

- completar SKU/EAN nuevos;
- reconciliar disponibilidad;
- construir estadísticas de 30/90 días;
- calcular Opportunity Score;
- refrescar el índice de búsqueda.

Esto ocurre después de los collectors y no cambia el límite individual de 25
minutos por tienda.

## Verificación obligatoria

En los logs debe aparecer:

```text
Monitor de Licores v5.4.0 · Catalog Intelligence & Reliability
Comparador cross-store: confianza ≥ 86%; top=30
Resiliencia de tiendas: El Mundo del Vino cada 12 h (tolerancia 15 min)
Estadísticas históricas...:
Opportunity Scores guardados:
```

Comprueba también en Telegram:

```text
/estado
/historial johnnie black 750
/oportunidades
/mejores
```

Una tienda no ejecutada por intervalo debe mostrarse como `DUE_SOON`, con una
hora exacta de próxima revisión. Una ejecución real correcta debe mostrarse
`HEALTHY`, con duración mayor que cero.

## Comprobación de Alembic

En Railway o localmente:

```bash
alembic current
alembic heads
```

Ambos deben terminar en:

```text
0008_catalog_intelligence
```

## Retroceso

Antes del deploy crea un respaldo de PostgreSQL. El código v5.3.4 no conoce las
funciones nuevas, aunque tolera que las columnas adicionales permanezcan. Para
un retroceso operativo rápido:

1. volver al commit v5.3.4;
2. conservar la base migrada;
3. no ejecutar `alembic downgrade` salvo que exista un respaldo verificado.

El downgrade elimina estadísticas, reglas manuales y estados de disponibilidad,
por lo que no se recomienda como primera medida.
