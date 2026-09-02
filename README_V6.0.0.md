# v6.0.0 — Watchlists

Primera versión de la rama 6.x. El objetivo es dejar de revisar manualmente el monitor y permitir que Telegram espere condiciones comerciales concretas sobre un producto canónico.

## Reglas disponibles

### Precio objetivo

```text
/vigilar johnnie black 750 bajo 25000
```

La condición se cumple cuando el mejor precio público vigente es menor o igual al objetivo.

### Opportunity Score mínimo

```text
/vigilar johnnie black 750 score 90
```

La condición se cumple cuando el Opportunity Score público persistido llega al umbral configurado.

### Nuevo mínimo histórico

```text
/vigilar johnnie black 750 minimo
```

Sólo notifica una ruptura real del mínimo histórico previo (`NEW_HISTORICAL_MIN`). El mismo mínimo no se vuelve a notificar en ciclos posteriores.

### Ventaja CAV

```text
/vigilar johnnie black 750 cav 3000
```

La condición se cumple únicamente cuando el ganador personal es `MEMBER/cav_member` y la ventaja frente al mejor precio público es al menos el monto configurado.

## Estado persistente

Las reglas viven en `telegram_favorites` para reutilizar resolución canónica, permisos por chat y la cola `favorite_alerts`. La migración `0013_watchlists` agrega:

- `min_opportunity_score`;
- `notify_on_new_historical_min`;
- `min_personal_advantage_clp`;
- `watch_state`.

`watch_state` conserva el estado de cada condición. Precio, score y ventaja CAV notifican sólo en transición `false -> true`. Los mínimos históricos guardan una clave formada por el mínimo nuevo y el mínimo anterior.

## Compatibilidad

- `/favorito`, `/avisar`, `/misfavoritos` y `/eliminarfavorito` siguen disponibles.
- Una alerta creada con `/avisar` aparece también en `/watchlist` porque ya posee precio objetivo.
- Si `/vigilar` crea el producto desde cero, no activa automáticamente los avisos clásicos de favorito (baja cualquiera, tienda nueva, cambio de ganador o reposición); sólo vigila la regla solicitada.
- Si el producto ya era favorito, se preservan sus preferencias previas.

## Telegram

```text
/watchlist
/quitarwatch ID
```

`/watchlist` muestra la mejor oferta pública actual y el estado vivo de todas las reglas configuradas.

## Base de datos

Requiere:

```text
alembic upgrade head
```

La revisión final debe ser `0013_watchlists`.
