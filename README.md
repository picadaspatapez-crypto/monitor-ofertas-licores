# Monitor de Ofertas de Licores — v4.1.0

Plataforma multi-tienda para recolectar catálogos, guardar historial de precios
en PostgreSQL y enviar reportes por Telegram.

## Tiendas activas

- Licor3B
- Líquidos.cl

## Flujo actual

```text
Collectors → PostgreSQL → análisis histórico → Telegram
```

La v4.1 incorpora el primer collector adicional sin modificar el pipeline. Cada
tienda conserva su propio historial, ejecuciones y estado de salud.

## Despliegue

Consulta `DEPLOY_V4.1.md`. No se agregan variables ni migraciones.

## Próxima versión

**v4.2:** diagnóstico y endurecimiento del collector de Líquidos usando los
primeros logs reales de Railway; luego comenzará el matching entre tiendas.
