# Despliegue v4.8 — Favoritos y alertas personalizadas

## 1. Actualizar el repositorio

Reemplaza el contenido del repositorio por esta versión y realiza el commit:

```text
Release v4.8 favorites and personalized alerts
```

La entrega es acumulativa: incluye todo lo desarrollado hasta v4.7.

## 2. Servicios Railway

No crees servicios nuevos.

- `monitor-ofertas-licores` continúa usando `/railway.toml` y el cron de 6 horas.
- `buscador-licores` continúa usando `/railway.search.toml` y permanece online.
- Ambos utilizan el mismo PostgreSQL y el mismo bot de Telegram.

El primer servicio que arranque aplicará automáticamente la migración:

```text
0006_telegram_bot_state -> 0007_telegram_favorites
```

## 3. Variables

No hay variables obligatorias nuevas. Mantén las existentes.

Variables opcionales del servicio `monitor-ofertas-licores`:

```env
FAVORITE_MIN_DROP_CLP=1
FAVORITE_ALERT_LIMIT=20
```

`FAVORITE_MIN_DROP_CLP` define la baja mínima en pesos que genera un aviso. El
valor predeterminado `1` avisa cualquier baja real. `FAVORITE_ALERT_LIMIT`
limita la cantidad de avisos personalizados enviados en una ejecución.

## 4. Probar Telegram

Después de que `buscador-licores` quede online, prueba:

```text
/favorito johnnie walker black 750
/misfavoritos
/avisar johnnie walker black 750 bajo 25000
/eliminarfavorito 1
```

La lista muestra un ID propio de cada favorito. Ese ID se usa para eliminarlo.

## 5. Cuándo se envían los avisos

Los favoritos se evalúan después de una revisión completa y saludable de todas
las tiendas. Esto evita avisos falsos cuando un collector falla o devuelve un
catálogo incompleto.

El bot avisa cuando:

- el mejor precio baja;
- se alcanza el precio objetivo;
- el producto aparece en una tienda nueva;
- cambia la tienda más barata;
- vuelve a estar disponible después de no aparecer.

El primer guardado establece la línea base. Si el precio ya cumple el objetivo,
el bot lo indica inmediatamente en la respuesta del comando.

## 6. Logs esperados

En `buscador-licores`:

```text
BOT Telegram listo: @TuBot; chats autorizados=[...].
Servicio interactivo v4.8.0 · Favorites & Personalized Alerts ...
```

Después de una ejecución del scraper:

```text
FAVORITOS PERSONALIZADOS · evaluados=..., encolados=..., enviados=..., fallidos=...
```
