# Deploy v5.8.4 — Licor3B Title Integrity Guard

Base requerida: **v5.8.3**.

## Qué corrige

Licor3B puede entregar, dentro de algunas tarjetas de categoría, un título contaminado por texto de una tarjeta/producto vecino. El caso observado fue:

`3 Vinos Montes Alpha Cabernet Sauvignon 3 Vinos Marques De Casa Concha Cabernet Sauvignon 750 ml`

para una URL cuyo producto real es `Vino Marqués de Casa Concha Cabernet Sauvignon 750 ml`.

v5.8.4 usa el slug estable de la URL del producto como guard cuando existe evidencia fuerte de contaminación, repara nombres persistidos de Licor3B, reconstruye el nombre canónico afectado y purga snapshots derivados para que se recalculen.

## Despliegue

1. Aplicar este hotfix sobre v5.8.3.
2. Commit + push.
3. No hay migraciones nuevas; Alembic debe seguir en `0012_commercial_intelligence`.
4. Ejecutar **un Run now** después del deploy para reparar los nombres persistidos y recalcular radar/minimos.
5. Revisar en logs `Títulos Licor3B reparados`.

## No cambia

- collectors de otras tiendas;
- scheduler;
- CAV;
- esquema PostgreSQL;
- política de packs de v5.8.3.
