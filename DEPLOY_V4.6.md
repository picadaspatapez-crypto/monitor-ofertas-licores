# Despliegue v4.6 — Catálogo unificado y buscador web

## 1. Actualizar el servicio cron existente

Reemplaza el repositorio por el contenido de la v4.6 y realiza el commit:

```text
Release v4.6 unified catalog and search engine
```

El servicio cron existente continúa usando:

```text
/railway.toml
```

No cambies su cron ni su Start Command. La próxima ejecución aplicará la
migración `0005_search_catalog` y actualizará el índice después del matching.

## 2. Crear el servicio web

En el mismo proyecto de Railway:

1. Agrega otro servicio conectado al mismo repositorio de GitHub.
2. Nómbralo, por ejemplo, `buscador-licores`.
3. En Settings, define **Railway Config File** como:

   ```text
   /railway.search.toml
   ```

4. Comparte o referencia la misma variable `DATABASE_URL` del PostgreSQL.
5. Agrega una clave privada larga:

   ```env
   SEARCH_ACCESS_TOKEN=una-clave-larga-y-dificil-de-adivinar
   ```

6. No configures Cron Schedule en este segundo servicio.
7. Genera un dominio público para el servicio web.

El archivo `railway.search.toml` inicia `/app/search_entrypoint.sh`, mantiene el
proceso activo y usa `/health` como healthcheck.

## 3. Abrir el buscador

Visita:

```text
https://TU-DOMINIO.up.railway.app/buscar
```

Ingresa la clave configurada en `SEARCH_ACCESS_TOKEN` y prueba consultas como:

```text
johnnie black 750
jack honey
mistral 35 1 litro
```

## 4. Variables opcionales

```env
SEARCH_RESULT_LIMIT=8
SEARCH_MAX_AGE_HOURS=72
```

`SEARCH_MAX_AGE_HOURS` impide mostrar publicaciones que llevan demasiado tiempo
sin ser observadas por los collectors.

## 5. Diagnóstico

El healthcheck público es:

```text
/health
```

Debe responder con `status: ok`. La búsqueda JSON, protegida por la misma clave,
está disponible en:

```text
/api/search?q=johnnie+black+750
```
