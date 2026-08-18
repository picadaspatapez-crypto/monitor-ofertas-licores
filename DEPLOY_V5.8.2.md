# Deploy v5.8.2 — Pack Identity Guard Hotfix

Base requerida: **v5.8.1 — Commercial Radar Visibility Hotfix**.

## Qué corrige

La versión anterior detectaba `Pack 6`, `6 botellas` y `6x750 ml`, pero podía interpretar como botella individual títulos reales como:

- `Casas Patronales Gran Reserva Cabernet Sauvignon X6 750 ml`
- `Casas Patronales Gran Reserva Carmenere X6 750 ml`
- `Cocotel Secreto Peruano Sour X6 1000 ml`
- `Vodka Eristoff Botella 700cc x6`

Eso permitía que un precio total o promocional de multipack quedara dentro de un master de botella individual y generara ahorros irreales.

## Cambios

1. Matching 2.0 reconoce también `X6 750 ml`, `x 6 750 ml`, `750cc x6`, `X12`, etc.
2. El comparador cross-store elimina multipacks antes de evaluar grupos, incluso si existe un match antiguo/manual/de EAN.
3. Los históricos de mercado sólo agregan publicaciones con `package_quantity = 1`.
4. Antes de recalcular históricos se reparan automáticamente cantidades de pack antiguas usando el parser v5.8.2.
5. `/radar` y `/minimos` excluyen snapshots cuyo ganador sea multipack, incluso antes de que se regenere el snapshot.
6. El comparador personal CAV aplica la misma barrera.

## Base de datos

No hay migraciones nuevas.

```text
Alembic head: 0012_commercial_intelligence
```

## Instalación

1. Respaldar PostgreSQL por seguridad habitual.
2. Copiar el contenido interior del hotfix sobre la raíz de la v5.8.1.
3. Commit + push.
4. Esperar el deployment exitoso de Railway.
5. Ejecutar **un solo Run now**.

El `Run now` es importante en esta corrección: recalcula `package_quantity`, vuelve a ejecutar Matching 2.0, reconstruye históricos comerciales y reemplaza los Opportunity Snapshots contaminados.

## Validación esperada

En el bloque de matching debería aumentar `Packs excluidos` si existían títulos `X6` no detectados anteriormente.

Después del ciclo:

- `/radar` no debe comparar `... X6 750 ml` contra una botella de 750 ml.
- `/minimos` no debe usar precios de packs como mínimo de la botella individual.
- Los rankings internos de una tienda pueden seguir mostrando packs como productos comerciales propios; la prohibición aplica a comparación cross-store y a inteligencia de botella individual.
