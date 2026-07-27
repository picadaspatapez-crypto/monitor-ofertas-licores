# Monitor de Ofertas de Licores — v4.2.0

Plataforma multi-tienda para recolectar catálogos, guardar historial de precios
en PostgreSQL y enviar reportes por Telegram.

## Tiendas activas

- Licor3B
- Líquidos.cl

## Cambio principal de v4.2

Telegram deja de mostrar un catálogo alfabético y presenta hasta **30 productos
ordenados por oportunidad de precio** en cada tienda.

El ranking considera:

1. La mayor baja real frente a la observación anterior.
2. El mayor descuento informado por la tienda.
3. El mayor ahorro absoluto en pesos.
4. El precio actual solamente como desempate final.

No se usa `MAX_PRODUCT_PRICE` ni ningún otro techo de precio. Un producto caro
puede aparecer si su baja o descuento lo justifica.

## Flujo actual

```text
Collectors → PostgreSQL → análisis histórico → ranking de precios → Telegram
```

## Despliegue

Consulta `DEPLOY_V4.2.md`. No se agregan migraciones ni variables obligatorias.
La variable antigua `MAX_PRODUCT_PRICE` puede permanecer en Railway, pero esta
versión la ignora completamente.

## Próxima versión

**v4.3:** periodicidad recomendada, resúmenes más breves y control de alertas
repetidas.
