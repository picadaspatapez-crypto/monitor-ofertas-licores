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

---

# Refuerzos v5.4

## Identificadores estructurados

Antes de depender del texto, el reconciliador busca:

1. EAN no vacío e idéntico;
2. SKU idéntico junto con marca y volumen compatibles;
3. reglas manuales persistentes;
4. matching textual conservador.

Un SKU no se considera global por sí solo porque distintas tiendas pueden
reutilizar la misma numeración interna.

## Reglas manuales

Equivalencia confirmada:

```bash
python -m app.matching.rules equivalence \
  "JW Black 750 cc" \
  "Johnnie Walker Black Label 750 ml"
```

Exclusión permanente:

```bash
python -m app.matching.rules exclusion \
  "Johnnie Walker Black + 2 vasos" \
  "Johnnie Walker Black Label 750 ml"
```

Las exclusiones tienen prioridad y evitan que la pareja vuelva a unificarse en
ejecuciones posteriores.

---

# Matching 2.0 — v5.7

## Jerarquía de evidencia

1. **Regla manual confirmada**: 100 %, persistente.
2. **EAN idéntico**: 100 %, salvo conflicto estructural imposible (formato, añada o ABV).
3. **SKU coincidente**: señal secundaria; solo se acepta si marca, volumen y el matching independiente superan 92 %.
4. **Firma exacta/alias**: nombre normalizado, volumen, variante y metadatos compatibles.
5. **Fuzzy conservador**: umbral operativo mínimo configurado, por defecto 86 %.
6. **Cerca del umbral**: no se fusiona; se envía a revisión humana.

## Conflictos duros

El reconciliador rechaza antes del scoring:

- botella vs pack/regalo;
- distinto volumen;
- añadas distintas cuando ambas están explícitas;
- graduaciones alcohólicas que difieren más de 1,5 puntos;
- marcas incompatibles;
- variantes explícitas incompatibles.

## Revisión humana

En el buscador privado:

```text
/matching/review
```

Cada tarjeta ofrece:

- **Mismo producto** → crea una regla `equivalence`;
- **No comparar** → crea una regla `exclusion`.

También se conserva la vía CLI:

```bash
python -m app.matching.review list --limit 20
python -m app.matching.review resolve 123 confirm --notes "EAN verificado"
python -m app.matching.review resolve 124 reject --notes "distinta edición"
```

Los pares que posteriormente superan el umbral automático se cierran como `auto_resolved` y dejan de aparecer en la cola.

## Catálogo canónico

`master_products` incorpora `canonical_fingerprint`, `abv_pct`, `vintage_year` e `identity_confidence`.
Los nombres observados se conservan en `canonical_aliases`, asociados al producto maestro y a su tienda de origen.
