# Despliegue v4.2 — Best Price Ranking

## Cambios

- 30 productos destacados por tienda en lugar de 20.
- Ranking por baja histórica real, descuento informado y ahorro absoluto.
- Eliminación del límite máximo de precio del código de configuración.
- El catálogo alfabético se reemplaza por `Mejores precios`.
- No hay migraciones nuevas.

## Pasos

1. Reemplazar en GitHub el contenido del repositorio por el contenido interior
   de este ZIP.
2. Commit sugerido:

```text
Release v4.2 best price ranking
```

3. En Railway, seleccionar **Deploy Latest Commit**.
4. No modificar PostgreSQL ni Telegram.
5. `MAX_PRODUCT_PRICE` puede borrarse de Railway, pero no es obligatorio: la
   aplicación ya no la lee.

## Señales esperadas en logs

```text
Monitor de Licores v4.2.0 · Best Price Ranking
Collectors habilitados: licor3b, liquidos
```

En Telegram aparecerán tres bloques cuando existan al menos 30 productos:

```text
🏆 Mejores precios 1-10 de 30
🏆 Mejores precios 11-20 de 30
🏆 Mejores precios 21-30 de 30
```
