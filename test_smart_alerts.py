# Licor3B: catálogo completo

El modo predeterminado es:

```env
LICOR3B_CATALOG_MODE=full
```

Recorre estas categorías raíz:

- Cervezas
- Espumantes
- Licores
- Otros
- Packs
- Piscos
- Rones
- Tequilas
- Vinos
- Vodkas
- Whisky

Los productos repetidos entre categorías se guardan una sola vez usando su URL canónica.

## Modo de contingencia

Para ejecutar únicamente la antigua página de ofertas:

```env
LICOR3B_CATALOG_MODE=offers
```

## Diagnóstico parcial

Para probar solo ciertas categorías:

```env
LICOR3B_CATALOG_MODE=full
LICOR3B_SECTIONS=whiskys,vinos,piscos
```

Al eliminar `LICOR3B_SECTIONS`, vuelve a recorrer las once categorías.

## Primera ejecución tras el cambio

La primera ejecución completa puede registrar muchos productos como nuevos porque antes la base contenía principalmente el catálogo de ofertas. Desde la segunda ejecución, las métricas de nuevos, desaparecidos y cambios de precio vuelven a representar cambios entre catálogos completos.
