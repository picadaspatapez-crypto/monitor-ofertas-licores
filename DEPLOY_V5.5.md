# Deploy v5.5.0 — Price Contexts & La Vinoteca

Base requerida: **v5.4.0 Catalog Intelligence & Reliability**.

## Qué cambia

- La Vinoteca se incorpora como collector activo mediante catálogo VTEX público.
- CAV se incorpora en **modo diagnóstico**: recolecta precios Normal, Oferta y Socio, pero no participa en el comparador público, buscador público, favoritos ni alertas comerciales.
- Se añade infraestructura general de precios contextuales (`PUBLIC`, `SALE`, `MEMBER`, preparada para `CARD_PROMO` y `COUPON`).
- Se crea una vista personal separada y no intrusiva. El comando `/personal` (alias `/miprecio`) muestra un preview que puede usar el precio socio CAV.
- El histórico y Opportunity Score públicos continúan usando únicamente tiendas `comparison_enabled=true`.

## Migración

La versión agrega Alembic `0009_price_contexts`.

Antes de desplegar, realiza un respaldo de PostgreSQL. Después aplica:

```bash
alembic upgrade head
```

El `entrypoint.sh` del proyecto ya ejecuta las migraciones normalmente en Railway. En logs debe quedar el head `0009_price_contexts`.

La migración:

1. añade `stores.comparison_enabled` y `stores.diagnostic_mode`;
2. crea `product_price_quotes`;
3. crea `price_quote_observations`;
4. crea `personal_opportunity_snapshots`;
5. hace backfill del precio público vigente de productos existentes.

No elimina historial previo.

## Primera ejecución

Se recomienda una ejecución manual una sola vez después del deploy para validar la migración y ambos collectors nuevos.

Logs esperados de La Vinoteca:

```text
La Vinoteca VTEX página 1: ...
...
RESUMEN DE EJECUCIÓN · La Vinoteca
Salud collector........: 🟢 HEALTHY
```

Logs esperados de CAV:

```text
CAV diagnóstico página 1: ...
...
RESUMEN DE EJECUCIÓN · CAV
```

En el resumen Telegram, CAV debe aparecer con `🧪` y `DIAGNÓSTICO`.

## Regla de seguridad de CAV

Mientras `diagnostic_mode=true` y `comparison_enabled=false`:

- CAV no puede ganar el comparador público.
- CAV no aparece en el buscador público.
- CAV no modifica mínimos/medias históricas públicas.
- Un fallo de CAV no bloquea favoritos ni hace fallar el ciclo operativo si las tiendas públicas funcionan.
- Los precios socio se almacenan como `MEMBER / cav_member / eligibility_required=true`.

## Validación

Después de la primera ejecución prueba:

```text
/estado
/buscar johnnie black 750
/oportunidades
/personal
```

`/buscar` y `/oportunidades` no deben mostrar CAV. `/personal` sí puede mostrar CAV cuando existe una coincidencia y el precio socio resulta ganador.

## Rollback

Si el código debe revertirse, vuelve al commit/tag de v5.4.0. No ejecutes `alembic downgrade` salvo que sea estrictamente necesario; dejar las tablas nuevas sin uso es más seguro que destruir datos recolectados.
