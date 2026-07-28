# Matching entre tiendas — v5.0

## Objetivo

Reconocer el mismo producto comercial en dos, tres o cuatro tiendas sin mezclar
variantes, volúmenes ni presentaciones incompatibles.

## Firma normalizada

Cada nombre se transforma en una firma con:

- tokens relevantes;
- marca inferida;
- variante;
- volumen en mililitros;
- cantidad de unidades;
- señales de pack, regalo o personalización.

Ejemplo compatible:

```text
Whisky Johnnie Walker Black Label 750 ml
Johnnie Walker Etiqueta Negra 75 cl
```

## Exclusiones automáticas

No se fusionan automáticamente:

- una botella individual con cajas o packs;
- productos de distinto volumen;
- variantes como Black Label y Red Label;
- regalos con vasos, copas, chocolates o bebidas;
- botellas personalizadas o grabadas;
- miniaturas y candidatos sin formato verificable;
- candidatos ambiguos con puntajes casi idénticos.

## Matching multi-tienda

Para cada publicación se selecciona el mejor candidato recíproco **por cada tienda
contraparte**. Esto permite que una publicación de Licor3B se relacione simultáneamente
con sus equivalentes en Líquidos, Tost y GradoÚnico.

No se usa un único “segundo mejor global”, porque en un catálogo de cuatro tiendas los
tres equivalentes correctos pueden tener nombres muy similares y parecer ambiguos entre sí.

## Confianza

El puntaje combina cobertura de palabras, Jaccard, similitud de secuencia, marca,
variante, volumen y cantidad. El umbral predeterminado continúa en 86 %.

## Persistencia

- `products.master_product_id`
- `product_matches.confidence`
- `product_matches.matching_method`
- `product_matches.review_status`

El comparador toma como máximo una publicación —la más barata— por tienda dentro de
cada producto maestro y vuelve a validar todos los pares antes de publicar una oportunidad.
