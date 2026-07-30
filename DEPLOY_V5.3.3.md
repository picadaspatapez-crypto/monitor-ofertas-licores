# Deploy v5.3.3 — Socomep Replacement

## Objetivo

Reemplazar La Barra por Socomep sin borrar datos históricos ni alterar PostgreSQL.

## Instalación

1. Descomprime el ZIP.
2. Sube a GitHub el contenido interior de la carpeta.
3. Usa el commit:

```text
Release v5.3.3 Socomep replacement
```

4. Railway desplegará `monitor-ofertas-licores` y `buscador-licores`.
5. Ejecuta `Run now` una sola vez para validar Socomep.

## Logs esperados

```text
Monitor de Licores v5.3.3 · Socomep Replacement: La Barra Disabled
Collectors habilitados: licor3b, liquidos, elmundodelvino, comercialjp, dondelanegra, lamodelo, socomep
Resiliencia de tiendas: El Mundo del Vino cada 12 h; La Barra deshabilitada; Socomep activo cada 6 h.
```

Luego:

```text
▶ Iniciando collector paralelo: Socomep
Socomep categoría 1/4: Licores
Socomep licores página 1: HTTP=200, ...
Resumen Socomep: ... salud=HEALTHY(...)
```

## Base de datos

No hay migraciones nuevas. En el primer ciclo, el registro de La Barra se marca inactivo.
Sus datos históricos permanecen almacenados, pero dejan de mostrarse como ofertas vigentes.

## Variables

No hay variables obligatorias nuevas. Se conservan:

```env
COLLECTOR_WORKERS=4
COLLECTOR_TIMEOUT_MINUTES=25
EL_MUNDO_INTERVAL_HOURS=12
```
