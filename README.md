# Monitor de Ofertas de Licores

**Versión actual: v5.8.0 — Commercial Intelligence 2.0.**

Plataforma chilena multi-tienda para recolectar precios, mantener historial,
comparar productos equivalentes, medir oportunidades reales y consultar el
catálogo desde web o Telegram.

## Tiendas activas

### Mercado público

- Licor3B
- Líquidos
- El Mundo del Vino
- Comercial JP
- Donde La Negra
- Distribuidora La Modelo
- Socomep
- La Vinoteca

### Fuente híbrida pública/personal

- CAV: participa en el mercado público sólo mediante precios `PUBLIC`/`SALE` sin elegibilidad y mantiene `MEMBER/cav_member` para el perfil personal.

La Barra, Tost y GradoÚnico permanecen fuera del registry activo.

## Novedades de v5.8

- **Opportunity Score v2:** pondera ahorro de mercado, posición histórica, rareza, confianza de matching, frescura y escasez.
- **Nuevo mínimo histórico:** compara el precio del run actual con el mínimo previo al ciclo y registra la ruptura en pesos y porcentaje.
- **Rareza de oferta:** mide con qué frecuencia el mercado estuvo dentro de 5% de su piso de 90 días y sólo la usa con historia suficiente.
- **Señales explicables:** `NEW_HISTORICAL_MIN`, `RARE_OFFER`, `AT_HISTORICAL_MIN`, `NEAR_HISTORICAL_MIN`, `MARKET_LEADER` y `NORMAL`.
- **Alertas comerciales deduplicadas:** nuevos mínimos y ofertas raras con baja real pueden notificarse automáticamente sin repetir el mismo precio en cada ciclo.
- **Telegram:** añade `/radar`, `/inteligencia` y `/minimos`.
- **Buscador web:** muestra badges de señal comercial, Score v2 y frecuencia de piso cuando existe historia suficiente.
- **Migración:** `0012_commercial_intelligence`.
- **Sin cambios de collectors:** scraping, scheduler, CAV híbrido y reglas de calidad/matching de v5.7.1 se conservan.

## Base heredada de v5.7

- Catálogo canónico con fingerprint, EAN/SKU, ABV, añada, formato y aliases.
- Matching 2.0 con conflictos duros y cola `/matching/review`.
- Data Quality Engine 0–100 con `CLEAN`, `WARNING` y `BLOCKED`.
- `/quality` y `/calidad` disponibles en Telegram.
- CAV híbrido: público sólo `PUBLIC`/`SALE`; `MEMBER` permanece personal.

## Novedades de v5.6

- CAV deja el modo diagnóstico y pasa a `personal_comparison_enabled=true`.
- El buscador web permite alternar entre **Mercado público** y **Con membresía CAV**.
- Los precios de socio solo se usan cuando su audiencia está habilitada en
  `PERSONAL_PRICE_AUDIENCES`.
- El historial contextual separa `PUBLIC`, `SALE` y `MEMBER` por audiencia.
- Opportunity Score personal usa ahorro, historia contextual, matching, frescura y escasez.
- Telegram añade `/miprecio`, `/personal` y `/historialsocio`.
- Alertas personales notifican bajas del precio MEMBER y ventajas relevantes frente al mejor precio público.
- Los precios `MEMBER` de CAV siguen aislados del comparador público; sus quotes `PUBLIC`/`SALE` sí pueden participar desde v5.7.1.

## Base heredada de v5.4

### Planificador verificable

- El Mundo del Vino conserva su intervalo de 12 horas.
- Una tolerancia de 15 minutos evita saltarse la revisión si Railway inicia el
  cron segundos antes del vencimiento.
- El estado `DUE_SOON` distingue un catálogo vigente reutilizado de una ejecución
  real.
- `/estado` informa último intento, última revisión HEALTHY, próxima revisión y
  fuente del collector.

### Disponibilidad real

- Cada publicación guarda disponibilidad, racha de ausencias, última fecha
  disponible y reactivación.
- Un producto solo se desactiva después de faltar en dos catálogos `HEALTHY`
  consecutivos.
- Capturas `DEGRADED`, `STALE`, `BROKEN` o fallidas nunca aumentan la racha.
- Los productos inactivos dejan de participar en búsqueda, comparación y
  favoritos; si reaparecen se registran como reposición.

### Historial y Opportunity Score

- Estadísticas de 30 y 90 días: mínimo, promedio y mediana.
- Mínimo histórico, frecuencia de descuento y días al precio actual.
- Opportunity Score de 0 a 100 con cinco componentes:
  diferencia de mercado, posición histórica, confianza del matching, frescura
  y escasez entre tiendas.
- Clasificaciones: Excelente, Muy buena, Buena, Normal y No destacada.

### Matching reforzado

- EAN exacto cuando la tienda lo entrega.
- SKU + marca + volumen como señal conservadora.
- Reglas manuales persistentes de equivalencia y exclusión.
- El Mundo del Vino captura SKU y código de barras de variantes; La Modelo y
  Donde La Negra conservan sus SKU públicos.

### Telegram y observabilidad

- Comparador ampliado a 30 resultados.
- Paginación con `/mas`.
- `/historial producto`, `/oportunidades` y `/mejores`.
- Reporte semanal de salud con tasa de éxito, duración, cobertura, rate limits y
  ejecuciones cercanas al límite de 25 minutos.
- Cada resumen identifica la fuente real del collector.

## Arquitectura Railway

```text
Postgres
   ▲
   ├── monitor-ofertas-licores
   │      cron cada 6 horas
   │      8 tiendas públicas base + CAV híbrido, máximo 4 workers
   │      matching + historial + Opportunity Score v2
   │
   └── buscador-licores
          web /buscar + API + bot Telegram permanente
```

## Despliegue

Consulta [`DEPLOY_V5.8.md`](DEPLOY_V5.8.md).

La versión incorpora la migración Alembic `0012_commercial_intelligence`. El
`entrypoint.sh` existente ejecuta `alembic upgrade head` antes del pipeline.

## Ejecución local

```bash
pip install -r requirements.txt
alembic upgrade head
python main.py
```

Buscador web y bot:

```bash
pip install -r requirements-search.txt
./search_entrypoint.sh
```

## Reglas manuales de matching

```bash
python -m app.matching.rules equivalence \
  "JW Black 750 cc" \
  "Johnnie Walker Black Label 750 ml" \
  --notes "Equivalencia validada"

python -m app.matching.rules exclusion \
  "Johnnie Walker Black + 2 vasos" \
  "Johnnie Walker Black Label 750 ml" \
  --notes "Pack contra botella individual"
```

## Pruebas

```bash
PYTHONPATH=. python -m pytest
```
