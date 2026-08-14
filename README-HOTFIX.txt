v5.7.0 — Canonical Catalog & Matching 2.0

BASE: v5.6.1

1. Haz respaldo de PostgreSQL.
2. Copia el contenido de este ZIP sobre la raíz de tu repositorio v5.6.1.
3. Reemplaza los archivos existentes cuando corresponda.
4. Haz commit + push y espera el deploy de Railway.
5. Confirma que Alembic queda en 0011_canonical_matching_quality.
6. Ejecuta un solo Run now para poblar calidad/catálogo canónico.
7. Revisa /quality y /matching/review en el buscador privado.

Este hotfix NO cambia collectors, frecuencia de ejecución, límite de 25 minutos ni
configuración CAV. Se concentra en identidad, matching y calidad de datos.
