MONITOR DE LICORES — HOTFIX / UPGRADE v5.6.0
Personal Pricing & CAV Activation

BASE REQUERIDA
- v5.5.3 Search UI Refresh

QUÉ HACE
- Activa CAV como fuente PERSONAL para precios socio, sin incorporarla al mercado público.
- Mantiene 8 tiendas públicas separadas de CAV.
- Añade modo de búsqueda "Con membresía CAV".
- Añade historial separado PUBLIC/SALE/MEMBER + audiencia.
- Activa Opportunity Score personal y ahorro real frente al mejor precio público.
- Añade alertas de baja MEMBER y ventajas de membresía.
- Añade /personal, /miprecio y /historialsocio en Telegram.

IMPORTANTE
- Incluye migración Alembic 0010_personal_pricing_activation.
- Haz respaldo de PostgreSQL antes de desplegar.
- No requiere usuario ni contraseña de CAV.
- CAV continúa sin contaminar /buscar público, /oportunidades públicas ni estadísticas públicas.

APLICACIÓN
1. Copia TODO el contenido de esta carpeta sobre la raíz de tu proyecto v5.5.3.
2. Reemplaza los archivos existentes conservando las rutas.
3. Commit + push.
4. Railway debe ejecutar: alembic upgrade head.
5. Tras un deployment exitoso, ejecuta un único Run now para validar/poblar estadísticas personales.

Consulta DEPLOY_V5.6.md para la validación posterior.
