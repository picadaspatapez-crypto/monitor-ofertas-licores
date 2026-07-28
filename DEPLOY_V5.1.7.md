# Deploy v5.1.7 — Shopify rate limit y resumen temprano

## Objetivo

Esta versión corrige dos comportamientos observados en producción:

1. El Mundo del Vino podía agravar un HTTP 429 al encadenar reintentos automáticos, JSON y HTML.
2. El resumen multi-tienda se enviaba después de matching, reindexación y favoritos, por lo que una tienda correcta como Comercial JP podía tardar en aparecer en Telegram.

## Cambios

- El HTTP 429 de El Mundo del Vino se maneja explícitamente.
- Se respeta `Retry-After`, limitado a una pausa segura entre 30 y 120 segundos.
- Se realiza un único reintento controlado.
- Un 429 persistente no activa inmediatamente el fallback HTML.
- Hay una pausa preventiva de 8 a 12 segundos entre categorías.
- Si una página posterior recibe 429, se conservan los productos ya recopilados en esa categoría.
- Una captura parcial suficiente se persiste con salud `DEGRADED`.
- El resumen global de Telegram se envía apenas terminan los collectors, antes de matching, reindexación y favoritos.

## Instalación

Reemplazar el contenido del repositorio con la versión completa o aplicar el hotfix sobre v5.1.6.

Commit sugerido:

```text
Release v5.1.7 rate-limit and early summary
```

No hay migraciones ni variables obligatorias nuevas.
