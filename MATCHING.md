# Matching entre tiendas — v4.5

## Objetivo

Reconocer cuándo dos publicaciones representan el mismo producto comercial sin
mezclar variantes ni formatos incompatibles.

## Firma normalizada

Cada nombre se transforma en una firma con:

- tokens relevantes;
- marca inferida;
- variante;
- volumen normalizado en mililitros;
- detección de pack o formato múltiple.

Ejemplo:

```text
Whisky Johnnie Walker Black Label 750 ml
Johnnie Walker Etiqueta Negra 75 cl
```

Ambos quedan con marca `johnnie walker`, variante `black`, volumen `750 ml` y
pueden compararse.

## Exclusiones automáticas

No se fusionan automáticamente:

- `Pack 6 cerveza 330 ml` con `Cerveza 330 ml`;
- `Whisky X 750 ml` con `Whisky X 1 litro`;
- `Johnnie Walker Black` con `Johnnie Walker Red`;
- productos sin volumen verificable;
- candidatos ambiguos.

## Puntaje

El confidence score combina:

- cobertura de palabras;
- similitud Jaccard;
- similitud de secuencia;
- compatibilidad de marca;
- compatibilidad de variante;
- igualdad de volumen.

Solo los matches con al menos 86 % se aceptan por defecto. Además, ambos
productos deben elegirse mutuamente como su mejor candidato.

## Persistencia

El resultado se guarda en:

- `products.master_product_id`;
- `product_matches.confidence`;
- `product_matches.matching_method`;
- `product_matches.review_status`.

Los productos maestros que quedan sin publicaciones se marcan como `merged`,
pero no se eliminan para conservar trazabilidad.
