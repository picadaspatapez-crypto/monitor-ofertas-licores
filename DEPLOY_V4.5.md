# Despliegue v4.5

## Instalación

1. Reemplaza el contenido del repositorio por el contenido interior del ZIP.
2. Haz commit y push:

```text
Release v4.5 cross-store matching and comparator
```

3. Railway desplegará automáticamente.
4. No modifiques PostgreSQL ni borres el historial.
5. No se requiere ninguna migración nueva.

## Variables

No hay variables obligatorias nuevas. Opcionalmente:

```env
CROSS_STORE_MATCH_MIN_CONFIDENCE_PERCENT=86
TELEGRAM_COMPARISON_LIMIT=20
TELEGRAM_WINNER_CHANGE_LIMIT=10
```

## Logs esperados

Después de completar ambos collectors:

```text
MATCHING Y COMPARACIÓN ENTRE TIENDAS
Productos actuales........: ...
Packs excluidos...........: ...
Matches aceptados.........: ...
Equivalencias verificadas.: ...
Oportunidades de precio...: ...
Cambios de ganador........: ...
```

La primera ejecución enviará el primer digest comparativo. Las siguientes solo
lo repetirán si cambia el ranking o vence el intervalo de 24 horas.
