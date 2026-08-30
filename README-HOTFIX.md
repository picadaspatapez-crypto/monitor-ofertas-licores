# v5.9.2 — Expansion Consolidation Hotfix

Aplicar sobre una instalación funcional de v5.9.1.2.

## Qué hace

- No modifica collectors.
- Agrega una auditoría de consolidación para las seis tiendas incorporadas en v5.9.
- Revisa por defecto las últimas 3 ejecuciones por tienda.
- Evalúa salud, estabilidad de cantidad, canonicalización, Data Quality, matching cercano al 86%, tiempos, brechas extremas y crecimiento del historial.
- Agrega `/auditoria` en Telegram.
- Puede enviar un reporte automático cada 24 horas mientras la expansión esté en observación; una vez STABLE, la confirmación se deduplica.

## Instalación

Reemplazar/agregar los archivos del ZIP conservando exactamente sus rutas. No borrar archivos que no aparezcan en el hotfix.

No hay migraciones nuevas de base de datos.

Variables opcionales de Railway:

```env
EXPANSION_AUDIT_REPORT=true
EXPANSION_AUDIT_INTERVAL_HOURS=24
EXPANSION_AUDIT_RUNS_PER_STORE=3
```

Si no se configuran, esos son los valores por defecto.

Después del deploy puedes ejecutar `/auditoria` directamente. No hace falta un Run now sólo para probar esta versión: utiliza el historial de runs ya almacenado.
