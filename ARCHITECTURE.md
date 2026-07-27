# Arquitectura implementada — v4.3

## Flujo de ejecución

```text
Railway Cron (cada 6 h)
        ↓
Collector Registry
        ↓
Licor3B ─────────┐
                 ├─→ persistencia + historial PostgreSQL
Líquidos ────────┘
        ↓
Análisis histórico y salud
        ↓
Política de alertas inteligentes
        ↓
Reserva deduplicada en alerts
        ↓
Telegram
        ↓
Proceso terminado
```

## Principios operativos

1. El proceso es de una sola pasada; no contiene un bucle infinito.
2. Railway controla la periodicidad y no se mantienen recursos activos entre ejecuciones.
3. Un collector fallido no impide ejecutar la tienda siguiente.
4. El historial de precios se guarda aunque Telegram falle.
5. Cada mensaje lógico se reserva en PostgreSQL antes del envío.
6. Los rankings idénticos no se repiten dentro del intervalo configurado.
7. Los productos no tienen techo de precio para ingresar al ranking.

## Módulos principales

```text
app/
├── collectors/       # Implementaciones independientes por tienda
├── pipeline/          # Orquestación de una ejecución completa
├── repositories/      # Escritura y lectura PostgreSQL
├── analyzers/         # Cambios históricos y salud del catálogo
├── notifications/     # Política que decide qué merece Telegram
├── reports/           # Formato de mensajes
├── services/          # Entrega a Telegram y estado de alertas
├── matching/          # Normalización inicial de productos
└── models.py          # Modelo SQLAlchemy
```

## Periodicidad

`railway.toml` configura `0 */6 * * *` y `restartPolicyType = "NEVER"`.
Railway inicia el contenedor, `entrypoint.sh` aplica Alembic, ejecuta el pipeline
y el proceso sale. Si una ejecución se solapa con la siguiente, Railway omite la
nueva ejecución.

## Política de alertas

### Inmediatas

- bajas reales que superen el umbral porcentual o absoluto;
- cambio a `DEGRADED` o `BROKEN`;
- cambio estructural o categoría fallida;
- recuperación a `HEALTHY`;
- excepción completa del collector.

### Digest

El top 30 se envía si su huella cambia o si vence el intervalo de refresco. La
huella incorpora posición, producto, precio actual, precio regular y descuento.

### Silenciosas

Una ejecución sana sin cambios relevantes se conserva en `scrape_runs` y
`price_observations`, pero no genera mensajes.

## v4.7 · Servicio interactivo

`buscador-licores` ejecuta dos componentes dentro del mismo contenedor:

```text
SearchServer (HTTP /buscar y /api/search)
TelegramSearchBot (long polling getUpdates)
                ↓
          PostgreSQL compartido
```

El web server mantiene el healthcheck de Railway. El worker de Telegram se
ejecuta en un hilo independiente, restringe los chats autorizados y persiste su
offset en `telegram_bot_state`.
