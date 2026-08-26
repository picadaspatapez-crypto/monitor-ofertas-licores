# Deploy v5.8.5 — Canonical Snapshot Consistency Guard

## Base requerida

Aplicar sobre **v5.8.4**. No contiene migraciones nuevas. Alembic debe permanecer en `0012_commercial_intelligence`.

## Problema corregido

En producción se observó un resultado de `/radar` cuyo título canónico seguía siendo:

`3 Vinos Montes Alpha Cabernet Sauvignon 3 Vinos Marques De Casa Concha Cabernet Sauvignon 750 ml`

aunque la publicación ganadora de Licor3B correspondía a `Vino Marques de Casa Concha Cabernet Sauvignon 750 ml`.

La causa no era ya el parser del collector. Un `OpportunitySnapshot` o `MasterProduct` legado podía sobrevivir a un relink y conservar el nombre antiguo. v5.8.5 valida la relación master↔winner tanto al persistir como al consultar.

## Instalación

1. Respaldar PostgreSQL como práctica habitual.
2. Copiar el contenido interior del hotfix sobre la raíz de v5.8.4, reemplazando archivos.
3. Commit + push.
4. Esperar deployment exitoso de Railway.
5. Ejecutar **un solo Run now** para retirar masters huérfanos, purgar snapshots inconsistentes y recalcular oportunidades.

## Qué revisar en logs

La línea de integridad ahora incluye:

```text
Títulos Licor3B reparados.: X; masters=Y; snapshots=Z; orphans=A; inconsistentes=B
```

`orphans` puede ser mayor que cero en el primer ciclo si quedaron masters históricos sin publicaciones.

## Validación funcional

Después del Run now:

```text
/radar
/minimos
```

El caso Marqués de Casa Concha debe mostrarse sin el prefijo `3 Vinos Montes Alpha...`.

## Base de datos

No ejecutar `alembic upgrade` manualmente por este hotfix si Railway ya lo hace en el entrypoint. No hay revisión nueva; el head continúa siendo:

```text
0012_commercial_intelligence
```
