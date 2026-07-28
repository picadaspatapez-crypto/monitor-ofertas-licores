# Despliegue v5.0 — Four-store Expansion

## Alcance

Esta versión incorpora Tost y GradoÚnico, amplía el sistema a cuatro tiendas y agrega
el resumen global que confirma el estado de todos los collectors en cada ejecución.

## Instalación

1. Descomprime el ZIP.
2. Sube a la raíz de la rama `main` el contenido interior de la carpeta.
3. No subas el ZIP ni una carpeta exterior adicional.
4. Commit sugerido:

```text
Release v5.0 four-store expansion
```

Railway desplegará los dos servicios conectados al repositorio.

## Servicio cron

`monitor-ofertas-licores` debe continuar usando:

```text
/railway.toml
```

Configuración esperada:

```toml
[deploy]
startCommand = "/app/entrypoint.sh"
restartPolicyType = "NEVER"
cronSchedule = "0 */6 * * *"
```

No hay variables obligatorias nuevas. `COLLECTOR_WORKERS` es opcional; el valor
predeterminado ahora es `4` y el máximo permitido también es `4`.

## Servicio interactivo

`buscador-licores` debe continuar usando:

```text
/railway.search.toml
```

Con las mismas variables existentes:

```text
DATABASE_URL
SEARCH_ACCESS_TOKEN
TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID o TELEGRAM_ALLOWED_CHAT_IDS
```

## Base de datos

No borres PostgreSQL. No hay migraciones nuevas: Alembic debe informar que ya está en
`0007_telegram_favorites`.

Las nuevas tiendas se crean automáticamente en la tabla `stores` durante su primera
ejecución.

## Primer ciclo esperado

En los logs deben aparecer casi simultáneamente:

```text
▶ Iniciando collector paralelo: Licor3B
▶ Iniciando collector paralelo: Líquidos
▶ Iniciando collector paralelo: Tost
▶ Iniciando collector paralelo: GradoÚnico
```

Al ser el primer ciclo de las dos tiendas nuevas, todos sus productos contarán como
nuevos. El matching, el índice de búsqueda y los favoritos se recalculan al final.

Telegram enviará un resumen compacto como:

```text
📊 Revisión multi-tienda completada

🟢 GradoÚnico ...
🟢 Licor3B ...
🟢 Líquidos ...
🟢 Tost ...
```

Los rankings extensos mantienen su política inteligente y no tienen que aparecer en
todas las ejecuciones.

## Comprobaciones

En Telegram:

```text
/estado
/buscar johnnie walker black 750
/misfavoritos
```

`/estado` debe mostrar las cuatro tiendas después de que finalice el primer cron v5.0.
