# v5.9.1.1 — Wave 2 Stabilization

Hotfix sobre **v5.9.1**. No modifica base de datos ni requiere migraciones.

## Corrige

1. **Licores.cl**: las fichas usan una única ruta `/producto/detalle` y diferencian el producto mediante `?id=N`. El canonicalizador común elimina query strings, por lo que v5.9.1 colapsaba todas las fichas a una sola identidad. Este hotfix preserva exclusivamente el `id` de producto para esta tienda, mantiene la paginación pública `page/per-page`, valida cobertura y conserva la semántica de precio vigente vs. precio tachado.
2. **Central Vinos y Licores**: cambia la categoría inválida `/espumante` por la ruta pública vigente `/espumantes`.
3. **Tienda de Vinos La Reina**: sin cambios.

## Archivos de aplicación

- `app/collectors/licorescl.py`
- `app/collectors/centralvinos.py`
- `app/version.py`

## Despliegue

Copiar/reemplazar estos archivos sobre v5.9.1, commit/push a GitHub y desplegar en Railway. No ejecutar Alembic adicional.
Después del deployment verde, ejecutar un único `Run now` y revisar específicamente `Licores.cl` y `Central Vinos y Licores`.
