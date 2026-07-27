# Ruta de v4.0 a v5.0

Se limita el avance a once entregas desplegables, incluida v5.0.

| Versión | Entrega principal |
|---|---|
| 4.0 | Base multi-tienda: metadata declarativa, registry validado y runner genérico. |
| 4.1 | Collector inicial de Líquidos.cl y persistencia separada por tienda. |
| 4.2 | Catálogo completo de Líquidos.cl, paginación y salud por sección. |
| 4.3 | Normalización común de nombres, volúmenes y packs. |
| 4.4 | Matching conservador entre Licor3B y Líquidos. |
| 4.5 | Comparación de precios por producto maestro. |
| 4.6 | Alertas Telegram multi-tienda y oportunidades. |
| 4.7 | Revisión manual de matches dudosos y trazabilidad. |
| 4.8 | API interna de consulta y búsqueda. |
| 4.9 | Dashboard web mínimo viable. |
| 5.0 | Plataforma estable: dashboard, comparación, historial y proceso documentado para nuevas tiendas. |

Cada ZIP debe poder reemplazar la versión anterior, ejecutar Alembic de forma segura y pasar su suite de pruebas antes de desplegarse.
