HOTFIX v5.8.5 — Canonical Snapshot Consistency Guard

Base: v5.8.4

Objetivo:
- eliminar snapshots master/winner inconsistentes;
- retirar masters huérfanos;
- impedir que /radar y /minimos muestren masters merged o winners relinked;
- sanear en lectura títulos Licor3B legados aunque el Product ya esté corregido.

No hay migraciones nuevas.
Después del deploy ejecutar un solo Run now.
Ver DEPLOY_V5.8.5.md.
