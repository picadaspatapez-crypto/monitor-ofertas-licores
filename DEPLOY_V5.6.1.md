# Deploy v5.6.1 — CAV Store Ranking Notifications

Base requerida: **v5.6.0 — Personal Pricing & CAV Activation**.

## Objetivo

Hacer que CAV participe en Telegram con el mismo bloque visual de **Mejores precios por tienda** que las demás fuentes, usando el precio socio CAV y sin incorporarla al mercado público.

## Cambios funcionales

Después de cada revisión CAV que termine `HEALTHY`, Telegram genera hasta 30 productos en bloques de 10:

```text
🏆 Mejores precios 1-10 de 30 · CAV

1. Producto
Precio actual: $36.000
Precio normal informado: $49.990
Descuento informado: 28%
Ahorro informado: $13.990
Motivo del ranking: precio socio CAV
https://cav.cl/...
```

El ranking se ordena primero por mayor descuento socio, luego por mayor ahorro absoluto y finalmente por menor precio.

CAV continúa con:

```text
comparison_enabled=false
personal_comparison_enabled=true
```

Por tanto, este cambio **no modifica** `/buscar` público, `/oportunidades` públicas ni el matching del mercado público.

## Persistencia y migraciones

No hay migraciones nuevas. El head continúa siendo:

```text
0010_personal_pricing_activation
```

## Despliegue

1. Aplicar el hotfix sobre v5.6.0.
2. Commit + push.
3. Esperar deployment correcto en Railway.
4. No es necesario ejecutar Alembic manualmente si el entrypoint habitual ya ejecuta `alembic upgrade head`.
5. Se recomienda un único **Run now** para validar inmediatamente el nuevo mensaje CAV.

## Resultado esperado

Tras un CAV `HEALTHY`, además de las alertas personales existentes, deben aparecer tres mensajes si hay al menos 30 precios MEMBER elegibles:

- `Mejores precios 1-10 de 30 · CAV`
- `Mejores precios 11-20 de 30 · CAV`
- `Mejores precios 21-30 de 30 · CAV`

Un reintento del mismo `run_id` no duplica ese ranking.
