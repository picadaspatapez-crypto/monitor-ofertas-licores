v5.5.1 — LA VINOTECA 206 + CAV RENDERED CATALOG HOTFIX
======================================================

BASE OBLIGATORIA: v5.5.0 Price Contexts & La Vinoteca.

Corrige:
- La Vinoteca: HTTP 206 de VTEX se acepta como respuesta válida y paginable.
- CAV: el collector deja de paginar HTML estático y renderiza el listado real con Playwright.

CAV SIGUE EN DIAGNÓSTICO y NO modifica el comparador público.
NO HAY MIGRACIONES NUEVAS. Alembic permanece en 0009_price_contexts.

Aplicación:
1. Copia el CONTENIDO de este hotfix sobre la raíz de v5.5.0.
2. Reemplaza archivos.
3. Commit + push.
4. Espera deploy exitoso en Railway.
5. Ejecuta un único Run now de validación.

Lee DEPLOY_V5.5.1.md antes del deploy.
