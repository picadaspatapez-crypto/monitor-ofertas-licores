v5.8.7 — PostgreSQL JSON DISTINCT Cross-store Hotfix

Aplicar sobre v5.8.6.

Archivos modificados:
- app/repositories/matching.py
- app/version.py
- tests/test_v5_8_7_postgres_json_distinct.py
- DEPLOY_V5.8.7.md

Corrige el error PostgreSQL "could not identify an equality operator for type json" de la etapa cross-store. No hay migraciones nuevas.
