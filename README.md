# Monitor de Ofertas de Licores

**Versión actual: v5.4.0 — Catalog Intelligence & Reliability.**

Plataforma chilena multi-tienda para recolectar precios, mantener historial,
comparar productos equivalentes, medir oportunidades reales y consultar el
catálogo desde web o Telegram.

## Tiendas activas

- Licor3B
- Líquidos
- El Mundo del Vino
- Comercial JP
- Donde La Negra
- Distribuidora La Modelo
- Socomep

La Barra, Tost y GradoÚnico permanecen fuera del registry activo. Sus collectors
y datos históricos no se borran, pero no participan en resultados vigentes.

## Novedades de v5.4

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
   │      7 collectors activos, máximo 4 workers
   │      matching + historial + Opportunity Score
   │
   └── buscador-licores
          web /buscar + API + bot Telegram permanente
```

## Despliegue

Consulta [`DEPLOY_V5.4.md`](DEPLOY_V5.4.md).

La versión incorpora la migración Alembic `0008_catalog_intelligence`. El
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
