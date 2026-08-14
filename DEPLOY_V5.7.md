# Deploy v5.7.0 — Canonical Catalog & Matching 2.0

## Base requerida

Aplicar sobre **v5.6.1**.

## Antes del deploy

1. Crear un respaldo/snapshot de PostgreSQL.
2. Confirmar que la rama desplegada corresponde a v5.6.1 estable.
3. Copiar el contenido interior del hotfix sobre la raíz del repositorio y reemplazar archivos.
4. Commit + push.

## Migración

v5.7 agrega:

`0011_canonical_matching_quality`

El `entrypoint.sh` existente debe ejecutar:

```bash
alembic upgrade head
```

Verificación:

```bash
alembic current
```

Debe terminar en:

```text
0011_canonical_matching_quality (head)
```

## Primer ciclo

Se recomienda **un solo Run now** después de confirmar que el deployment y la migración
terminaron correctamente. Ese ciclo poblará scores de calidad, fingerprints y aliases para
las publicaciones observadas.

No lanzar varias ejecuciones manuales consecutivas.

## Qué revisar

En los logs de la etapa multi-tienda:

```text
Calidad CLEAN/WARN/BLOCK..:
Revisión matching nueva...:
Revisión matching pendiente:
Maestros canónicos actual.:
Aliases canónicos vistos..:
```

En el buscador privado:

- `/quality`
- `/matching/review`
- `/buscar`

La presencia de publicaciones `BLOCKED` no significa que el collector haya fallado: indica
que v5.7 las conservó pero evitó que influyeran en el comparador.

## Rollback

El rollback de código puede hacerse regresando a v5.6.1. Las nuevas columnas/tablas son
aditivas y v5.6.1 no las usa.

No se recomienda ejecutar `alembic downgrade` en producción salvo que exista un motivo
específico y un respaldo reciente.
