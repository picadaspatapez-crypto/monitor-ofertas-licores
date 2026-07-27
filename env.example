# MATCHING.md

## Propósito

Reconocer cuándo publicaciones con nombres distintos representan el mismo producto comercial.

## Estrategia por etapas

1. EAN exacto.
2. Clave normalizada exacta.
3. Marca + variante + volumen.
4. Coincidencia difusa con umbral.
5. Revisión manual.

## Implementación actual

La versión inicial extrae el volumen y genera una clave normalizada conservadora.

Ejemplos:

```text
Johnnie Walker Black 750 ml
Whisky Johnnie Walker Black 750cc
```

Ambos eliminan palabras genéricas y normalizan el volumen a `750`.

## Seguridad de los emparejamientos

En esta etapa no se deben fusionar automáticamente claves diferentes. Es preferible crear dos productos maestros antes que mezclar productos distintos y contaminar las comparaciones de precio.

## Próximas mejoras

- catálogo de marcas;
- variantes y añadas;
- packs y número de unidades;
- graduación alcohólica;
- EAN;
- revisión manual desde dashboard;
- similitud difusa explicable.
