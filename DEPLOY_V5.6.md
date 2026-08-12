# Deploy v5.6.0 — Personal Pricing & CAV Activation

## Base requerida

Aplicar sobre **v5.5.3 — Search UI Refresh**.

## 1. Respaldo

Antes del deploy, crear respaldo de PostgreSQL y conservar el commit/ZIP de v5.5.3.

## 2. Variables

No se requieren credenciales de CAV. La configuración recomendada es:

```env
PERSONAL_PRICE_AUDIENCES=cav_member
PERSONAL_ALERTS_ENABLED=true
PERSONAL_ALERT_MIN_DROP_PERCENT=5
PERSONAL_ALERT_MIN_DROP_CLP=1000
PERSONAL_ALERT_MIN_ADVANTAGE_CLP=1000
PERSONAL_ALERT_LIMIT=10
```

`PERSONAL_PRICE_AUDIENCES` controla qué precios con elegibilidad pueden usar la vista personal. El valor `cav_member` habilita el precio socio CAV.

## 3. Migración

El entrypoint debe ejecutar:

```bash
alembic upgrade head
```

Head esperado:

```text
0010_personal_pricing_activation
```

La migración:

- agrega `stores.personal_comparison_enabled`;
- convierte CAV de diagnóstico a fuente personal activa;
- amplía `personal_opportunity_snapshots`;
- crea `price_context_statistics`.

No elimina historial ni productos.

## 4. Primera ejecución

Después del deployment se recomienda **un Run now** para poblar las estadísticas contextuales y recalcular Opportunity Score personal.

En logs deben aparecer líneas similares a:

```text
Monitor de Licores v5.6.0 · Personal Pricing & CAV Activation
Históricos contextuales....: ...
Opportunity Scores personales: ...
Telegram personal: ...
```

CAV debe aparecer como fuente personal, no como diagnóstico:

```text
🟣 CAV
1118 productos · HEALTHY · PERSONAL
```

El resumen del mercado público debe continuar contabilizando 8 tiendas públicas.

## 5. Validación web

En `/buscar` deben existir dos modos:

- `Mercado público`
- `Con membresía CAV`

Una búsqueda pública nunca debe incluir CAV. En modo personal, CAV puede ganar con una etiqueta `Precio socio`.

## 6. Validación Telegram

```text
/miprecio johnnie black 750
/personal
/historialsocio johnnie black 750
```

## 7. Rollback

Si la aplicación presenta un problema, volver al código v5.5.3. No ejecutar downgrade de la migración salvo que sea estrictamente necesario; las columnas/tablas nuevas son compatibles con el código anterior mientras no se usen.
