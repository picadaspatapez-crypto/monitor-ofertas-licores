HOTFIX v5.6.1 — CAV Store Ranking Notifications

BASE REQUERIDA
- v5.6.0 — Personal Pricing & CAV Activation

QUÉ HACE
- Después de cada revisión CAV HEALTHY, Telegram envía el ranking CAV con el mismo formato "Mejores precios" del resto de las tiendas.
- El Precio actual del ranking CAV es el precio MEMBER/cav_member.
- El Precio normal informado es el precio normal publicado por CAV.
- Calcula descuento y ahorro normal -> socio.
- El motivo del ranking se identifica como "precio socio CAV".
- Se mantienen activos "Tus mejores ventajas CAV" y las alertas de bajas MEMBER.
- CAV continúa fuera del comparador público.

MIGRACIONES
- Ninguna. Alembic sigue en 0010_personal_pricing_activation.

APLICACIÓN
1. Copiar el contenido de este hotfix sobre la raíz de v5.6.0.
2. Reemplazar los archivos existentes.
3. Commit + push.
4. Esperar el deploy de Railway.
5. Se recomienda un Run now para validar el nuevo ranking de CAV.
