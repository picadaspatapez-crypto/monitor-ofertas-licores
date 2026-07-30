# Arquitectura implementada — v5.0

## Servicios Railway

```text
Railway Cron · monitor-ofertas-licores
        ↓
Collector Registry
        ↓
┌─────────────┬──────────────┬──────────┬─────────────┐
│ Licor3B     │ Líquidos     │ Tost     │ GradoÚnico │
│ Playwright  │ Playwright   │ HTTP     │ HTTP        │
└─────────────┴──────────────┴──────────┴─────────────┘
        ↓
PostgreSQL: productos, historial, runs y alertas
        ↓
Matching multi-tienda + catálogo de búsqueda
        ↓
Comparación + favoritos + resumen global
        ↓
Telegram
```

El segundo servicio, `buscador-licores`, permanece activo y comparte la misma base:

```text
SearchServer (HTTP /buscar y /api/search)
TelegramSearchBot (long polling)
                ↓
          PostgreSQL compartido
```

## Paralelismo

La configuración predeterminada es `COLLECTOR_WORKERS=4`. Cada collector tiene su
propia sesión de base de datos. Solo dos workers abren Chromium; Tost y GradoÚnico
utilizan `requests`, por lo que el aumento de concurrencia no implica cuatro navegadores.

Dentro de una tienda las categorías siguen procesándose secuencialmente para limitar
bloqueos, CAPTCHA y consumo de recursos.

## Flujo posterior a la recolección

```text
Collect
  ↓
Persist + historial por tienda
  ↓
Reconcile cross-store matches
  ↓
Analyze price opportunities
  ↓
Refresh unified search catalog
  ↓
Evaluate personalized favorites
  ↓
Send compact all-store summary
```

Un collector fallido no cancela los otros. El resumen final siempre incluye los cuatro
resultados de la ejecución, mientras los rankings extensos conservan su deduplicación.

## Módulos principales

```text
app/
├── collectors/       # Implementaciones independientes por tienda
├── pipeline/          # Orquestación concurrente y etapas posteriores
├── repositories/      # Escritura y lectura PostgreSQL
├── analyzers/         # Cambios históricos y comparación multi-tienda
├── notifications/     # Política y deduplicación
├── reports/           # Telegram, comparación y resumen global
├── services/          # Entrega y estado de alertas
├── matching/          # Firmas, equivalencias y grupos maestros
├── search/            # Catálogo unificado, web y API
├── favorites/         # Seguimiento y precios objetivo
└── telegram_bot/      # Interfaz interactiva
```

## Periodicidad

`railway.toml` configura `0 */6 * * *` y `restartPolicyType = "NEVER"`.
El cron inicia, aplica Alembic, ejecuta una sola pasada y termina. El buscador utiliza
`railway.search.toml`, no tiene cron y permanece online.

## Estado y observabilidad

- `scrape_runs` conserva salud, cobertura, páginas, productos y métricas por sección.
- `/estado` consulta la última ejecución de cada tienda activa.
- Telegram recibe un resumen compacto por ejecución aunque no cambie ningún ranking.
- Alertas extensas y comparativas siguen sujetas a huella e intervalo de refresco.


## v5.3.3 — Registry operativo

El registry activo contiene siete tiendas: Licor3B, Líquidos, El Mundo del Vino, Comercial JP, Donde La Negra, Distribuidora La Modelo y Socomep. En cada ejecución se sincroniza `stores.is_active`; una tienda retirada conserva su historia pero queda fuera de resultados vigentes.
