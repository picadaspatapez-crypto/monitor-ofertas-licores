# Monitor de Ofertas de Licores — v4.8.0

Plataforma multi-tienda para **Licor3B** y **Líquidos.cl**. Recolecta catálogos
en paralelo, conserva historial en PostgreSQL, compara productos equivalentes y
permite buscar o seguir productos desde Telegram.

## Novedades de v4.8

- Favoritos privados por chat autorizado.
- Comando `/favorito` para seguir un producto.
- Comando `/avisar ... bajo ...` para definir un precio objetivo en CLP.
- Comandos `/misfavoritos` y `/eliminarfavorito ID`.
- Avisos por baja de precio, objetivo alcanzado, tienda nueva, cambio de ganador
  y reposición.
- Una sola notificación combina todos los eventos del mismo producto y revisión.
- Cola persistente de alertas con estados `pending`, `sent` y `failed`.
- Evaluación únicamente cuando todos los collectors terminan `HEALTHY`.
- Migración Alembic `0007_telegram_favorites`.
- Sin servicios Railway ni variables obligatorias adicionales.

## Arquitectura

```text
monitor-ofertas-licores (cron cada 6 horas)
  ├─ Licor3B + Líquidos
  ├─ matching y comparación
  ├─ actualiza catálogo
  └─ evalúa y envía alertas de favoritos

PostgreSQL
  ├─ catálogo e historial
  ├─ favoritos por chat
  └─ cola de alertas personalizadas

buscador-licores (siempre online)
  ├─ buscador web
  └─ bot Telegram
```

## Comandos Telegram

```text
/buscar johnnie black 750
/favorito johnnie black 750
/avisar johnnie black 750 bajo 25000
/misfavoritos
/eliminarfavorito 3
/estado
/ayuda
```

También se puede buscar escribiendo un producto sin comando.

## Despliegue

Consulta [`DEPLOY_V4.8.md`](DEPLOY_V4.8.md).
