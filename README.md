# Monitor de Ofertas de Licores — v4.5.0

Plataforma multi-tienda para **Licor3B** y **Líquidos.cl**. Recolecta ambos
catálogos en paralelo, conserva historial en PostgreSQL, envía alertas
inteligentes por Telegram y ahora compara productos equivalentes entre tiendas.

## Novedades de v4.5

Después de terminar los dos collectors, el pipeline ejecuta:

```text
Productos de Licor3B + Productos de Líquidos
                    ↓
Normalización de nombre, marca, variante y volumen
                    ↓
Exclusión de packs y formatos ambiguos
                    ↓
Matching conservador con confidence score
                    ↓
Productos maestros compartidos
                    ↓
Comparación de precios
                    ↓
Telegram: tienda más barata, ahorro y enlaces
```

### Reglas de seguridad

El sistema no compara automáticamente:

- packs, cajas, combos o estuches;
- productos sin volumen verificable;
- volúmenes diferentes;
- marcas incompatibles;
- variantes diferentes, por ejemplo Black Label y Red Label;
- candidatos ambiguos con puntajes casi idénticos.

El umbral predeterminado de confianza es **86 %**.

### Reporte comparativo

Telegram puede mostrar:

```text
Johnnie Walker Black 750 ml

🥇 Líquidos: $21.990
   Licor3B: $24.990
Ahorro: $3.000 (12,0 %)
Confianza del match: 96 %
```

El ranking comparativo:

- no tiene techo máximo de precio;
- ordena por mayor diferencia porcentual y luego ahorro en CLP;
- incluye hasta 20 oportunidades por defecto;
- se reenvía cuando cambia o cada 24 horas;
- avisa cuando cambia la tienda ganadora.

## Ejecución

Railway ejecuta el cron cada seis horas:

```cron
0 */6 * * *
```

Licor3B y Líquidos se procesan en paralelo con dos workers. Al terminar ambos,
se ejecuta el comparador en una sola transacción de PostgreSQL.

## Variables opcionales de v4.5

```env
CROSS_STORE_MATCH_MIN_CONFIDENCE_PERCENT=86
TELEGRAM_COMPARISON_LIMIT=20
TELEGRAM_WINNER_CHANGE_LIMIT=10
```

No es necesario agregarlas en Railway; esos valores ya son los predeterminados.

## Base de datos

v4.5 reutiliza las tablas existentes `master_products`, `product_matches`,
`products`, `price_observations` y `alerts`. **No incluye una migración nueva**.

## Despliegue

Consulta [`DEPLOY_V4.5.md`](DEPLOY_V4.5.md).
