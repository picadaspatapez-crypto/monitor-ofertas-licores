# Despliegue v5.1.1 — Tost Grid & Rate-Limit Fix

1. Reemplaza el contenido del repositorio con el contenido interior del ZIP.
2. Commit sugerido: `Release v5.1.1 Tost grid and rate-limit fix`.
3. Railway desplegará el monitor y el buscador.
4. Ejecuta `Run now` en el cron del monitor.

No se agregan migraciones ni variables obligatorias. El límite por tienda sigue siendo 25 minutos.

Logs esperados en Tost:

```text
Tost whisky página 1: ... productos=aprox. 40 ...
Tost whisky página 2: ... nuevos=>0 ...
```

Si Tost responde 429, el collector mostrará una pausa adaptativa y reintentará respetando `Retry-After`.
