HOTFIX v5.8.0 — Commercial Intelligence 2.0

BASE REQUERIDA
v5.7.1 — Quality Command & CAV Public Market

APLICACIÓN
1. Crear respaldo de PostgreSQL.
2. Copiar el contenido de este hotfix sobre la raíz del repositorio v5.7.1.
3. Reemplazar los archivos existentes conservando las rutas.
4. Commit + push.
5. Confirmar que Railway ejecuta `alembic upgrade head` y queda en `0012_commercial_intelligence`.
6. Ejecutar un único Run now después de un deployment exitoso.

QUÉ CAMBIA
- Opportunity Score v2.
- Frecuencia de piso de 90 días.
- Nuevo mínimo histórico comparado contra el historial previo al run actual.
- Señales comerciales explicables.
- Alertas deduplicadas para nuevos mínimos y ofertas raras con baja real.
- Telegram /radar, /inteligencia y /minimos.
- Badges comerciales en el buscador web.

QUÉ NO CAMBIA
- Collectors.
- Scheduler.
- Máximo de workers y límite por collector.
- Matching 2.0 / Data Quality.
- Política híbrida pública/personal de CAV.

Consulta DEPLOY_V5.8.md antes de desplegar.
