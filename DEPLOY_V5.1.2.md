# Deploy v5.1.2

## Objetivo

Corregir los dos hallazgos observados en Railway:

- Tost devolvía siempre el carrusel de 11 recomendaciones porque el catálogo principal se carga dinámicamente.
- GradoÚnico respondía 404 al solicitar `?page=1`, aunque la categoría sin ese parámetro estaba disponible.

## Instalación

1. Reemplaza el contenido del repositorio por el contenido interior del ZIP.
2. Commit sugerido: `Release v5.1.2 Tost browser and GradoUnico routes`.
3. No modifiques PostgreSQL ni las variables actuales.
4. Ejecuta `Run now` en el cron para validar.

## Configuración

Se conserva el límite por collector:

```env
COLLECTOR_TIMEOUT_MINUTES=25
```

Tost pasa a usar Playwright, por lo que durante la ejecución pueden existir tres navegadores simultáneos: Licor3B, Líquidos y Tost.

## Logs esperados

Tost debe mostrar más de 11 productos en categorías grandes y páginas distintas:

```text
Tost whisky página 1/4: ... productos=... nuevos=...
Tost whisky página 2/4: ... nuevos=>0
```

GradoÚnico debe abrir primero la URL sin `page=1`:

```text
GradoÚnico preflight: origen=https://www.gradounico.cl, HTTP=200
GradoÚnico whisky página 1: HTTP=200
```

Si una tienda sigue incompleta, la captura no se persiste y se conserva el último catálogo confiable.

## Base de datos

No hay migraciones nuevas. Alembic continúa en `0007_telegram_favorites`.
