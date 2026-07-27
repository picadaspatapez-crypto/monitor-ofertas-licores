# Despliegue v4.0 — Multi-store Foundation

## Alcance exacto

Esta versión prepara el núcleo multi-tienda sin activar todavía una segunda tienda. Licor3B mantiene su collector y comportamiento actual. La siguiente entrega, v4.1, agregará Líquidos.cl usando el nuevo contrato.

## Cambios operacionales

- No agrega variables de entorno.
- No agrega migraciones Alembic.
- No borra ni reinicia datos.
- Mantiene `entrypoint.sh`: primero `alembic upgrade head`, luego `python main.py`.
- Sincroniza los metadatos declarados de Licor3B con la fila existente en `stores`.

## Instalación

1. Conserva una copia o tag de la v3.0 actual.
2. Reemplaza el contenido del repositorio por el contenido de este directorio.
3. Sube los cambios a GitHub.
4. Railway desplegará el último commit automáticamente o mediante **Deploy Latest Commit**.

Commit sugerido:

```text
Release v4.0 multi-store foundation
```

## Logs esperados

Al comenzar:

```text
Monitor de Licores v4.0.0 · Multi-store Foundation
Collectors habilitados: licor3b
```

Al terminar:

```text
RESUMEN GLOBAL MULTI-TIENDA
Collectors registrados...: 1
Collectors correctos......: 1
Collectors fallidos.......: 0
```

## Validaciones realizadas

```text
Python compileall: correcto
Pytest: 10 passed
Alembic head: 0003_scrape_run_observability
Registry: licor3b válido y único
```

No se ejecutó un scraping real desde el entorno de generación porque no dispone de acceso de red al sitio. El collector de Licor3B no fue alterado salvo por mover sus metadatos al contrato declarativo.
