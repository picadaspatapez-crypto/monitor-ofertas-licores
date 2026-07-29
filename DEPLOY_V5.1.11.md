# Deploy v5.1.11 — El Mundo del Vino: catálogo global Shopify

Esta versión reemplaza las solicitudes por colección de El Mundo del Vino por un único feed global paginado:

```text
/products.json?limit=250&page=1
/products.json?limit=250&page=2
/products.json?limit=250&page=3
```

El collector clasifica los productos localmente y conserva una captura parcial como `DEGRADED` si Shopify limita una página posterior. No agrega variables ni migraciones.

## Hotfix desde v5.1.10

Reemplazar:

```text
app/collectors/elmundodelvino.py
app/version.py
```

Commit sugerido:

```text
Release v5.1.11 El Mundo global Shopify catalog
```
