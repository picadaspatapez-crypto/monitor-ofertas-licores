# Deploy v5.5.3 — Search UI Refresh

Base requerida: **v5.5.2 Pagination Boundary & CAV Sharded Catalog Hotfix**.

## Objetivo

Actualizar exclusivamente la experiencia visual del buscador web ahora que los ocho collectors públicos se mantienen estables. La versión no cambia scraping, matching, scheduler, Telegram, persistencia ni reglas de precios.

## Cambios visibles

- nueva barra superior de **Monitor de Licores** con versión y modo `Mercado público`;
- portada más compacta y orientada a comparación;
- buscador sticky y responsive;
- panel de pulso del catálogo con:
  - tiendas públicas activas;
  - productos comparables vigentes;
  - precios vigentes;
  - ventana de frescura configurada;
- accesos rápidos a búsquedas frecuentes;
- tarjetas de resultados con:
  - confianza del matching;
  - Opportunity Score;
  - mejor precio público;
  - ahorro frente a la segunda tienda;
  - promedio y mínimo de 90 días cuando existen;
  - ranking de ofertas por tienda;
  - enlace directo a cada publicación;
- mejor adaptación móvil;
- pantalla de acceso renovada;
- contenido escapado y sin dependencias frontend externas.

## Qué NO cambia

No se modifican:

- collectors de La Vinoteca, CAV ni las demás tiendas;
- `comparison_enabled` de CAV;
- reglas de matching;
- `/api/search`;
- comandos Telegram;
- scheduler;
- base de datos;
- migraciones Alembic.

CAV continúa en diagnóstico y **no participa** en el panel de mercado público ni en los resultados públicos.

## Base de datos

No hay migraciones nuevas.

Alembic debe permanecer en:

```text
0009_price_contexts
```

## Aplicación

1. Parte desde v5.5.2 estable.
2. Copia el contenido del hotfix sobre la raíz del repositorio.
3. Reemplaza los archivos existentes.
4. Commit + push.
5. Espera a que Railway despliegue el servicio web.
6. Abre `/buscar` y fuerza una recarga del navegador (`Ctrl+F5`) si conserva CSS anterior.

No es necesario ejecutar `Run now` del collector para validar esta versión, porque el cambio es del servicio web. Si ambos servicios comparten el mismo repositorio, Railway puede redeplegarlos, pero el código de collectors no cambia.

## Validación esperada

En `/buscar` sin consulta deben aparecer:

- `Monitor de Licores`;
- `Mercado público`;
- métricas del catálogo;
- búsquedas rápidas;
- tres tarjetas explicativas.

Al buscar un producto deben aparecer tarjetas con:

```text
Coincidencia ...%
Opportunity Score .../100
Mejor precio público
Comparación por tienda
```

La API mantiene el mismo contrato:

```text
GET /api/search?q=...
```

## Rollback

Restaura desde v5.5.2:

- `app/search/web.py`
- `app/search/static/search.css`
- `app/version.py`

No hay downgrade de base de datos.
