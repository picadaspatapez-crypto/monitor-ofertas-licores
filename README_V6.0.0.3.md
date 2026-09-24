# v6.0.0.3 — WooCommerce Availability-Aware Guard

Hotfix de estabilidad para el parser WooCommerce compartido por **Tienda de Vinos La Reina** y **El Brindis**.

## Problema corregido

Una página válida puede mantener productos agotados visibles con URL, nombre y precio. El parser los excluía correctamente del catálogo activo, pero el guard estructural seguía contando sus URLs como productos que debían persistirse. Si más de la mitad de una página estaba agotada, el guard interpretaba la exclusión deliberada como un fallo del parser.

Caso observado en Vinos La Reina / Espumantes página 2:

- 14 tarjetas / URLs de producto;
- 9 marcadas explícitamente `AGOTADO`;
- 5 disponibles y parseadas;
- resultado anterior: falso `parser WooCommerce no confiable`.

## Nuevo criterio

1. Cada tarjeta con disponibilidad explícita `AGOTADO`, `sin stock`, `out of stock` o `sold out` se clasifica como **agotada reconocida**.
2. Esas tarjetas continúan fuera del catálogo activo.
3. El guard calcula `activos_esperados = urls_producto - agotados_reconocidos`.
4. El umbral fail-closed de 50% se aplica sólo a `activos_esperados`, redondeando hacia arriba.
5. Una tarjeta desconocida/no parseable no se considera agotada por inferencia; debe contener un marcador explícito.

## Resultado esperado

Una página con 14 tarjetas, 9 agotadas y 5 activas debe producir `tarjetas=14, productos=5` sin degradar la sección. Si las 5 activas no se pueden parsear con cobertura suficiente, el guard sigue fallando.

No hay cambios en PostgreSQL, matching, watchlists, CAV ni scheduler.
