# Changelog

## v4.1.0 — Líquidos Collector

- Segundo collector activo: Líquidos.cl.
- Descubrimiento de categorías con respaldo.
- Soporte para carga infinita, cargar más y siguiente.
- Parser de productos y precios que excluye precio por litro.
- Deduplicación global y membresía de categorías.
- Métricas, historial y Telegram independientes por tienda.
- Sin variables ni migraciones nuevas.

## 2.0.0

- Introduce collectors, pipeline, repositories, analyzers y reports.
- Convierte Licor3B en un collector reutilizable.
- Mantiene compatibilidad con imports v1.
- Conserva el esquema y el historial PostgreSQL.
- Añade pruebas básicas de normalización e informes.

## 2.1 - Observabilidad
- Resumen final estructurado en logs y Telegram.
- Duración, páginas y tarjetas procesadas.
- Productos nuevos, actualizados, con bajas, alzas y sin cambios.
- Conteo de productos no observados en la ejecución.
- Cambios reales calculados contra el precio previo en PostgreSQL.
- Catálogo mostrado en orden alfabético.

## v2.2 — Catálogo completo Licor3B

- El collector deja de depender exclusivamente de `/product-category/ofertas/`.
- Recorre las once categorías raíz del catálogo y todas sus páginas.
- Deduplicación global por URL de producto entre categorías.
- Estadísticas y reportes incluyen cantidad de secciones recorridas.
- `LICOR3B_CATALOG_MODE=offers` permite volver al comportamiento anterior.
- `LICOR3B_SECTIONS` permite ejecutar categorías específicas para diagnóstico.
- Se corrigió la renovación real del contexto de Playwright durante reintentos CAPTCHA.

## v3.0 — Licor3B final

- Descubrimiento automático de categorías con fallback seguro.
- Eliminación del modo configurable: siempre se recorre el catálogo completo.
- Aislamiento de errores por categoría.
- Resumen y duración por categoría.
- Detección de cambios estructurales.
- Deduplicación global y categorías de origen en el dominio.
- Collector Health Score.
- Persistencia de observabilidad mediante Alembic 0003.
- Resumen de salud y categorías en Telegram.

## v4.0 — Multi-store Foundation

- Incorpora `StoreMetadata` como contrato declarativo de cada tienda.
- Elimina del pipeline los metadatos hardcodeados de Licor3B.
- Valida keys, slugs y connector keys duplicados al iniciar.
- Sincroniza metadatos de tiendas existentes sin una migración nueva.
- Agrega resumen global de collectors al finalizar la ejecución.
- Publica la versión en logs mediante `app/version.py`.
- Añade pruebas del registry y un roadmap de máximo once entregas hasta v5.0.
- No cambia el comportamiento de recolección de Licor3B.
