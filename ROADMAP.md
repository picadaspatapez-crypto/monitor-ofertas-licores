# Estado v5.7

**v5.7.0 — Canonical Catalog & Matching 2.0** implementa el catálogo canónico, la cola de revisión manual y el Data Quality Engine.

Siguiente línea propuesta:

- **v5.7.1**: solo estabilización si producción revela casos borde.
- **v5.8.0**: Commercial Intelligence 2.0, mínimos históricos y rareza de ofertas.
- **v5.9.0**: expansión controlada con nuevas tiendas.

---

# Roadmap

## Versiones completadas

- **v5.2**: Donde La Negra y Distribuidora La Modelo.
- **v5.3**: estabilización de las tiendas nuevas.
- **v5.3.3**: La Barra sale de la operación activa y Socomep la reemplaza.
- **v5.3.4**: El Mundo del Vino migra a Storefront GraphQL con control estricto de rate limit.
- **v5.4.0**: inteligencia de catálogo, disponibilidad real, historial 30/90 días,
  Opportunity Score, matching SKU/EAN, paginación Telegram y reporte semanal.

## Próximas líneas

- **v5.4.1**: estabilización de métricas, reglas manuales y consultas de historial
  con datos reales de Railway.
- **v5.5**: nuevas tiendas solo después de confirmar calidad del matching y tiempo
  total del pipeline.
- **v5.6**: presupuesto de compra, margen de reventa y ranking de cartera.

## Estado operativo en v5.4

- Licor3B: activo.
- Líquidos: activo.
- El Mundo del Vino: activo cada 12 horas, Storefront GraphQL y scheduler con gracia.
- Comercial JP: activo.
- Donde La Negra: activo, conserva SKU cuando la API lo entrega.
- Distribuidora La Modelo: activo, paginación dinámica y código público como SKU.
- Socomep: activo cada 6 horas.
- La Barra, Tost y GradoÚnico: deshabilitados y excluidos de ofertas vigentes.
