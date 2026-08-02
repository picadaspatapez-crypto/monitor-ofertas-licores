# Deploy v5.3.4 — El Mundo Storefront API Hardening

## Requisito

Este hotfix se aplica únicamente sobre **v5.3.3 Socomep Replacement**.

## Archivos incluidos

```text
.env.example
app/collectors/elmundodelvino.py
app/version.py
README-HOTFIX.txt
DEPLOY_V5.3.4.md
```

## Instalación

1. Descomprime el ZIP.
2. Entra en la carpeta `v5.3.4-el-mundo-storefront-api-hotfix`.
3. Copia su contenido interior sobre la raíz del repositorio v5.3.3.
4. Conserva las mismas rutas y acepta reemplazar los archivos existentes.
5. Sube los cambios a GitHub con un commit como:

```text
Release v5.3.4 El Mundo Storefront API hardening
```

6. Espera el despliegue normal de Railway.
7. No ejecutes varios `Run now` seguidos. Espera un ciclo en el que corresponda
   revisar El Mundo del Vino.

## Variables Railway

Se mantiene obligatoriamente:

```env
EL_MUNDO_INTERVAL_HOURS=12
```

Variables opcionales nuevas:

```env
EL_MUNDO_STOREFRONT_API_VERSION=2026-07
EL_MUNDO_STOREFRONT_ACCESS_TOKEN=
```

El modo normal no necesita token. Puedes omitir ambas variables opcionales; el
código usará `2026-07` y acceso tokenless. No escribas comillas ni la palabra
`null` en el token.

## Cambios operativos

- Fuente principal: Shopify Storefront GraphQL.
- Dominio permanente: `elmundodelvino-cl.myshopify.com`.
- Contexto de precios y mercado: Chile.
- Paginación por cursor: 75 productos por solicitud.
- Máximo de 15 páginas.
- Espera inicial aleatoria de 45 a 90 segundos.
- Pausa de 5 a 8 segundos entre páginas.
- Un solo reintento ante HTTP 429 o GraphQL `THROTTLED`.
- Respeto de `Retry-After`; espera de 90 segundos si falta.
- Corte inmediato ante HTTP 429 persistente, 430 o 403.
- Sin probar otros hosts después de una respuesta de bloqueo.
- Fallback a `products.json` solo ante fallas no relacionadas con bloqueo.
- Reutilización del último snapshot `HEALTHY` cuando el catálogo no puede
  renovarse.

## Log esperado

```text
Monitor de Licores v5.3.4 · El Mundo Storefront API Hardening
El Mundo del Vino: jitter inicial de ...s...
✓ El Mundo del Vino Storefront API página 1: ...
✓ El Mundo del Vino Storefront API página 2: ...
Resumen El Mundo del Vino: fuente=shopify_storefront_graphql, completo=sí, salud=HEALTHY(100)
```

## Criterios de aceptación

- `fuente=shopify_storefront_graphql`.
- Estado `HEALTHY(100)`.
- `completo=sí`.
- Cantidad plausible de productos, idealmente superior a 120.
- Ningún fan-out de hosts después de 429, 430 o 403.
- En el ciclo intermedio de seis horas se reutiliza el catálogo por la política
  de revisión cada doce horas.

## Si todavía aparece HTTP 429 o 430

No fuerces ejecuciones manuales repetidas. El monitor conservará el snapshot
anterior. El siguiente escalón técnico es Shopify Web Bot Auth con firmas
Ed25519 y un directorio JWKS público.

## Base de datos

No existen migraciones nuevas. No borrar PostgreSQL ni ejecutar Alembic
manualmente.
