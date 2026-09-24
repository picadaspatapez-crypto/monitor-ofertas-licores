# Deploy v6.0.0.3

1. Aplicar el hotfix sobre **v6.0.0.2**.
2. Commit/push a GitHub y desplegar normalmente en Railway.
3. No hay migración nueva; Alembic continúa en `0013_watchlists`.
4. Ejecutar un solo `Run now` y observar **Tienda de Vinos La Reina**.
5. En Espumantes página 2 es válido ver muchas `tarjetas` y menos `productos` si el resto está explícitamente agotado. La categoría ya no debe fallar por ese motivo.
6. Señal esperada: todas las secciones terminan `success`; si el resto de tiendas también está sano/STALE recuperable, favoritos y watchlists dejan de omitirse por Vinos La Reina.
7. Si aparece el nuevo error `parser WooCommerce no confiable` con `activos_esperados=...`, entonces sí existe pérdida real de cobertura en tarjetas activas y no debe bajarse el guard.
