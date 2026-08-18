# Deploy v5.8.0 — Commercial Intelligence 2.0

## Base requerida

Aplicar sobre **v5.7.1 — Quality Command & CAV Public Market**.

v5.8 no modifica collectors, paginación, scheduler ni la política híbrida de CAV. El cambio se concentra en análisis histórico, Opportunity Score, alertas y presentación.

## Antes del deploy

1. Crear un respaldo/snapshot de PostgreSQL.
2. Confirmar que la rama desplegada corresponde a v5.7.1 estable.
3. Copiar el contenido interior del hotfix sobre la raíz del repositorio y reemplazar archivos.
4. Commit + push y esperar que Railway termine el deployment.

## Migración

v5.8 agrega:

`0012_commercial_intelligence`

El `entrypoint.sh` existente debe ejecutar:

```bash
alembic upgrade head
```

Verificación:

```bash
alembic current
```

Debe terminar en:

```text
0012_commercial_intelligence (head)
```

La migración es aditiva. No elimina precios, productos, matching, favoritos ni historial.

## Primer ciclo

Se recomienda **un solo Run now** después de confirmar deployment y migración.

Ese ciclo recalcula las estadísticas de 90 días, la frecuencia de precios cercanos al piso y los Opportunity Scores v2. También genera la primera clasificación comercial de cada comparación.

Las alertas de `RARE_OFFER` exigen una baja real en la publicación durante ese run, por lo que desplegar v5.8 no debería producir una avalancha de alertas sólo por recalcular el histórico.

## Señales esperadas

En logs:

```text
Inteligencia comercial v2: alertas=sí; score raro ≥ 85; frecuencia piso ≤ 15%; historia mínima=6 observaciones.
Nuevos mínimos históricos.:
Ofertas poco frecuentes....:
Cerca/en mínimo histórico..:
```

Telegram:

```text
/radar
/minimos
```

El buscador web incorpora badges como `Nuevo mínimo`, `Oferta rara`, `Cerca del mínimo` y `Líder de mercado`.

## Variables opcionales

```text
COMMERCIAL_ALERTS_ENABLED=true
COMMERCIAL_ALERT_MIN_SCORE=85
COMMERCIAL_MIN_HISTORY_OBSERVATIONS=6
COMMERCIAL_RARE_FREQUENCY_PERCENT=15
COMMERCIAL_NEAR_HISTORICAL_MIN_PERCENT=3
COMMERCIAL_ALERT_LIMIT=8
```

Los valores por defecto son conservadores y no requieren configuración adicional para el primer deploy.

## Alertas automáticas

v5.8 envía alertas comerciales para:

- `NEW_HISTORICAL_MIN`: nuevo mínimo histórico confirmado frente al historial previo al run actual.
- `RARE_OFFER`: precio en la zona baja del histórico, poco frecuente, score suficiente y baja real durante el run.

La deduplicación se hace por producto, tipo de señal y precio, por lo que el mismo mínimo al mismo precio no se repite en cada ciclo.

## CAV

CAV conserva el modelo híbrido de v5.7.1:

- mercado público: sólo `PUBLIC`/`SALE` sin elegibilidad;
- perfil personal: `MEMBER/cav_member` cuando corresponda.

v5.8 no mezcla precios socio con el mercado público.

## Rollback

El rollback de código puede hacerse regresando a v5.7.1. Las columnas nuevas son aditivas y v5.7.1 no depende de ellas.

No se recomienda ejecutar `alembic downgrade` en producción salvo que exista un motivo concreto y un respaldo reciente.
