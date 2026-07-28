# Despliegue v5.0.1 — GradoÚnico Connection Resilience

Este hotfix corrige las esperas repetidas cuando GradoÚnico no acepta conexiones desde Railway.

## Qué cambia

- Se prueban `www.gradounico.cl` y `gradounico.cl` antes de recorrer el catálogo.
- El preflight no reintenta y utiliza tiempos de espera breves.
- Tras dos errores TCP consecutivos se abre un circuit breaker y se omiten las categorías restantes.
- El collector queda como fallido, por lo que no se marcan sus productos históricos como ausentes.
- Licor3B, Líquidos y Tost continúan normalmente; el comparador usa las tiendas exitosas.

## Instalación

Reemplaza el repositorio por el contenido interior del ZIP y usa:

```text
Release v5.0.1 GradoUnico connection resilience
```

No cambies Railway, PostgreSQL ni las variables. No hay migraciones nuevas.

## Logs esperados cuando el sitio está bloqueado o caído

```text
⚠ GradoÚnico preflight falló: https://www.gradounico.cl: ConnectTimeout ...
⚠ GradoÚnico preflight falló: https://gradounico.cl: ConnectTimeout ...
✖ Error en collector gradounico ... circuit breaker ...
```

El fallo completo debe resolverse en pocos segundos o decenas de segundos, no en once categorías de casi un minuto.

## Logs esperados cuando vuelve a estar accesible

```text
GradoÚnico preflight: origen=https://www.gradounico.cl, HTTP=200, ...
GradoÚnico categoría 1/11: Packs
```
