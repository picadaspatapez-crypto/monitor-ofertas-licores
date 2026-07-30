# Deploy v5.3.2 — Store Resilience

Esta versión estabiliza las dos fuentes más variables sin crear servicios ni migraciones.

## Política operativa

- El Mundo del Vino se intenta cada 12 horas.
- En los ciclos intermedios se reutiliza el último `ScrapeRun` HEALTHY para matching, búsqueda y resumen.
- Una captura parcial o un fallo de red no reemplaza el catálogo confiable: queda como `STALE`.
- La primera página con HTTP 429 corta el collector inmediatamente.
- Entre páginas posteriores se esperan 12–20 segundos.
- La Barra queda `PAUSED` y solo realiza un preflight liviano cada 168 horas.
- Mientras el preflight no encuentre productos públicos, no abre Chromium, no consulta sitemap y no genera alerta roja.

## Variables opcionales

```env
EL_MUNDO_INTERVAL_HOURS=12
LABARRA_PREFLIGHT_INTERVAL_HOURS=168
```

No es necesario agregarlas: esos son los valores predeterminados.

## Deploy

Commit sugerido:

```text
Release v5.3.2 store resilience
```

No hay migraciones nuevas. Railway mantiene el cron cada seis horas y el límite de 25 minutos por tienda.
