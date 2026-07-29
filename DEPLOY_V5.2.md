# Deploy v5.2 — Seven Store Expansion

## Tiendas activas

1. Licor3B
2. Líquidos
3. El Mundo del Vino
4. Comercial JP
5. La Barra
6. Donde La Negra
7. Distribuidora La Modelo

## Despliegue

1. Reemplaza el repositorio con el contenido interior del ZIP.
2. Commit sugerido: `Release v5.2 seven store expansion`.
3. No crees servicios nuevos y no borres PostgreSQL.
4. El monitor conserva `/railway.toml`; el buscador conserva `/railway.search.toml`.
5. No hay migraciones ni variables obligatorias nuevas.

## Operación

- Máximo de cuatro collectors simultáneos; los restantes quedan en cola.
- Límite de 25 minutos por tienda.
- La Barra usa Playwright por su catálogo dinámico.
- Donde La Negra y La Modelo usan HTTP/HTML público.
- Matching, buscador, favoritos y Telegram incorporan automáticamente las tres tiendas.

## Primer ciclo

Busca en Railway:

```text
Collectors habilitados: licor3b, liquidos, elmundodelvino, comercialjp, labarra, dondelanegra, lamodelo
```

La primera ejecución puede enviar rankings y productos nuevos de las tres tiendas añadidas.
