HOTFIX v5.4.0 — CATALOG INTELLIGENCE & RELIABILITY
==================================================

BASE OBLIGATORIA
----------------
v5.3.4 — El Mundo Storefront API Hardening

CONTENIDO
---------
Este ZIP contiene únicamente archivos nuevos o modificados respecto de v5.3.4,
respetando exactamente las rutas del proyecto.

APLICACIÓN
----------
1. Descomprime el ZIP.
2. Abre la carpeta v5.4-catalog-intelligence-reliability-hotfix.
3. Copia todo su contenido sobre la raíz del repositorio v5.3.4.
4. Acepta reemplazar archivos y conservar las rutas.
5. Haz commit y push a GitHub.
6. Railway ejecutará alembic upgrade head antes de iniciar el monitor.

IMPORTANTE
----------
- Incluye la migración 0008_catalog_intelligence.
- Respaldar PostgreSQL antes del primer deploy.
- No borrar el volumen ni crear una base nueva.
- No aplicar este hotfix sobre v5.3.3 o versiones anteriores.
- Revisar DEPLOY_V5.4.md antes de desplegar.

VALIDACIÓN DEL PAQUETE
----------------------
141 pruebas automatizadas aprobadas.
El hotfix fue aplicado sobre una copia limpia de v5.3.4 y la suite completa fue
ejecutada nuevamente sobre esa copia.
