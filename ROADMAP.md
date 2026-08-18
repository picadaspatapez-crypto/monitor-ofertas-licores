# Estado v5.8

**v5.8.0 — Commercial Intelligence 2.0** implementa Opportunity Score v2, detección de nuevos mínimos históricos, rareza de la zona de precio y alertas comerciales explicables.

Siguiente línea propuesta:

- **v5.8.1**: sólo estabilización si producción revela casos borde en señales históricas.
- **v5.8.2**: hotfix de identidad de multipacks (`X6`, `x6`) y saneamiento de históricos/radar; sin migración.
- **v5.9.0**: expansión controlada con dos nuevas tiendas, priorizando APIs estructuradas.
- **v6.0.0**: dashboard avanzado, watchlists por umbral y analítica de compra.

---

# Roadmap

## Versiones completadas

- **v5.3.3**: Socomep reemplaza La Barra.
- **v5.3.4**: El Mundo del Vino migra a Shopify Storefront GraphQL.
- **v5.4.0**: disponibilidad real, historial 30/90 días, Opportunity Score v1 y scheduler con tolerancia.
- **v5.5.x**: La Vinoteca, infraestructura multiprecio, CAV sharded y renovación del buscador web.
- **v5.6.x**: activación de precios personales CAV y rankings automáticos por Telegram.
- **v5.7.0**: catálogo canónico, Matching 2.0 y Data Quality Engine.
- **v5.7.1**: `/quality` en Telegram y CAV híbrido público/personal.
- **v5.8.0**: Commercial Intelligence 2.0, mínimos históricos y rareza de ofertas.

## Estado operativo

- Licor3B: activo.
- Líquidos: activo.
- El Mundo del Vino: activo con intervalo de 12 horas y Storefront GraphQL.
- Comercial JP: activo.
- Donde La Negra: activo.
- Distribuidora La Modelo: activo.
- Socomep: activo.
- La Vinoteca: activa mediante VTEX.
- CAV: fuente híbrida; `PUBLIC`/`SALE` puede participar en mercado público y `MEMBER` permanece en perfil personal.
- La Barra, Tost y GradoÚnico: deshabilitados.

## v5.8 — Commercial Intelligence 2.0

Objetivos completados:

1. Opportunity Score v2 con componente explícito de rareza.
2. Frecuencia de piso de 90 días.
3. Comparación contra mínimo histórico previo al run actual.
4. Señales `NEW_HISTORICAL_MIN`, `RARE_OFFER`, `AT_HISTORICAL_MIN`, `NEAR_HISTORICAL_MIN` y `MARKET_LEADER`.
5. Alertas automáticas deduplicadas de mínimos y ofertas raras.
6. `/radar` y `/minimos` en Telegram.
7. Señales y Score v2 en buscador web y reportes.
8. Persistencia de la explicación comercial para auditoría.

## v5.9 — Expansión controlada

Propuesta:

- investigar dos tiendas nuevas;
- priorizar Shopify Storefront, VTEX, WooCommerce o APIs públicas antes de Playwright;
- exigir calidad y matching antes de activar una tienda en el comparador;
- mantener máximo cuatro collectors paralelos y 25 minutos por collector.

## v6.0 — Dashboard y watchlists

Propuesta:

- watchlists por precio objetivo;
- alertas por Opportunity Score mínimo;
- alertas por ventaja CAV frente al mercado;
- dashboard avanzado de históricos, salud y cartera de oportunidades;
- evaluación posterior de rentabilidad/reventa sólo con costos verificables.
