# Deploy v4.1.0 — Líquidos Collector

Esta versión activa el segundo collector del sistema: **Líquidos.cl**.

## Instalación

1. Reemplaza el contenido del repositorio por el contenido de este ZIP.
2. No cambies las variables existentes en Railway.
3. Commit sugerido:

```text
Release v4.1 Líquidos collector
```

4. Ejecuta **Deploy Latest Commit**.

## Qué deberías ver

```text
Monitor de Licores v4.1.0 · Líquidos Collector
Collectors habilitados: licor3b, liquidos
```

Después de Licor3B comenzará:

```text
Líquidos catálogo: categorías=...
Líquidos categoría 1/...: Packs
```

Al terminar aparecerá un resumen separado para cada tienda y un resumen global.

## Sin cambios de base de datos

No hay migraciones nuevas. La tabla `stores` registrará Líquidos automáticamente
mediante la infraestructura multi-tienda de v4.0.

## Comportamiento del collector

- Descubre las categorías raíz desde el menú.
- Usa una lista segura de respaldo si el menú no puede leerse.
- Fuerza modalidad de despacho web programado.
- Soporta carga infinita, botones «Cargar más» y paginación «Siguiente».
- Deduplica productos por URL canónica.
- Excluye el precio por litro al interpretar precios.
- Continúa aunque falle una categoría.
- Registra métricas de salud y reportes Telegram independientes.
