# Deploy v5.1.6 — El Mundo del Vino Resilient Shopify Fallback

Esta versión corrige capturas intermitentes de cero productos en El Mundo del Vino.

## Estrategia

1. Intenta el feed JSON de la colección Shopify.
2. Si no está disponible, usa HTML.
3. Ante HTML vacío, reintenta con host alternativo, bypass de caché y diagnóstico de respuesta.
4. Conserva el último catálogo confiable si todas las estrategias fallan.

No agrega migraciones ni variables.
