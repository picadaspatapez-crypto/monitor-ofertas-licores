# Deploy v5.8.3 — Canonical Pack Repair & Economic Sanity Guard

Base requerida: **v5.8.2**.

## Objetivo

v5.8.2 detectaba correctamente títulos `X6`/`X24`, pero una identidad canónica creada antes de esa corrección podía seguir mezclando una botella individual y un multipack. En ese caso el ganador podía ser una botella (`package_quantity=1`) y el nombre maestro seguir siendo `X6`, por lo que el filtro del ganador no bastaba.

v5.8.3 repara esos masters históricos y agrega defensas independientes en matching, comparación y presentación.

## Despliegue

1. Respaldar PostgreSQL.
2. Aplicar el contenido del hotfix sobre la raíz de v5.8.2.
3. Commit + push.
4. Esperar deployment HEALTHY en Railway.
5. Ejecutar **un solo Run now**.
6. Revisar el bloque `MATCHING Y COMPARACIÓN ENTRE TIENDAS`.

No hay migraciones nuevas. Alembic permanece en:

`0012_commercial_intelligence`

## Señales esperadas en logs

- `Pack identities reparadas.: <masters> masters; <productos> productos`
- `Snapshots pack purgados....: <n>`
- `Packs excluidos...........: <n>`

Después del run, `/radar` y `/minimos` no deben mostrar identidades canónicas `X6`, `X12`, `X24`, etc. como botellas individuales.
