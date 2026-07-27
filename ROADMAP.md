# ROADMAP.md

# Plataforma de Inteligencia de Precios - Monitor de Licores

## Visión

Construir una plataforma capaz de monitorear automáticamente múltiples
tiendas chilenas, almacenar el historial de precios y detectar
oportunidades reales de compra y reventa basándose en datos del mercado,
no únicamente en los descuentos informados por las tiendas.

------------------------------------------------------------------------

# Fase 1 - Recolección de datos (En progreso)

## Objetivos

-   Scrapers independientes por tienda.
-   Playwright para sitios con protección anti-bots.
-   PostgreSQL como almacenamiento central.
-   Ejecución automática en Railway.
-   Alertas por Telegram.

### Tiendas objetivo

-   ✅ Licor3B
-   ⏳ Líquidos
-   ⏳ La Barra
-   ⏳ Donde La Negra
-   ⏳ La Modelo
-   ⏳ Jumbo
-   ⏳ Lider
-   ⏳ Santa Isabel
-   ⏳ Tottus

------------------------------------------------------------------------

# Fase 2 - Normalización

Cada producto deberá transformarse a un formato común.

Ejemplo:

-   Johnnie Walker Black Label 750 ml
-   Whisky Johnnie Walker Black 750cc
-   JW Black 750

↓

Producto único.

Se desarrollará un motor de coincidencia basado en marca, volumen,
categoría y reglas de normalización.

------------------------------------------------------------------------

# Fase 3 - Historial de precios

Guardar diariamente:

-   fecha
-   tienda
-   precio
-   disponibilidad
-   URL

Esto permitirá:

-   variación diaria
-   mínimo histórico
-   máximo histórico
-   precio promedio
-   tendencias

------------------------------------------------------------------------

# Fase 4 - Comparación entre tiendas

Para un mismo producto:

-   precio más bajo
-   precio promedio
-   diferencia porcentual
-   ranking por tienda

Aquí nace el concepto de "oferta real".

------------------------------------------------------------------------

# Fase 5 - Opportunity Score

El puntaje combinará factores como:

-   diferencia respecto al promedio del mercado
-   diferencia respecto al mínimo histórico
-   estabilidad del precio
-   potencial de reventa
-   frecuencia de descuentos
-   disponibilidad

Resultado esperado:

Score 0--100 con clasificación:

-   Excelente
-   Muy buena
-   Buena
-   Normal
-   No recomendable

------------------------------------------------------------------------

# Fase 6 - Dashboard

Visualización de:

-   productos
-   histórico
-   mejores ofertas
-   evolución de precios
-   filtros por tienda
-   filtros por categoría
-   búsqueda

------------------------------------------------------------------------

# Fase 7 - Inteligencia

Funciones futuras:

-   predicción de bajadas de precio
-   estimación de precio de reventa
-   recomendaciones de compra
-   reportes semanales
-   ranking de tiendas

------------------------------------------------------------------------

# Principios del proyecto

1.  Los datos tienen prioridad sobre los descuentos publicitarios.
2.  Todo precio debe almacenarse.
3.  Las decisiones deben basarse en evidencia.
4.  Los scrapers deben ser independientes entre sí.
5.  El sistema debe ser modular y fácilmente ampliable.

------------------------------------------------------------------------

# Estado actual

## Infraestructura

-   GitHub
-   Railway
-   PostgreSQL
-   Playwright
-   Telegram

## Estado

El proyecto ya se encuentra en funcionamiento y puede recopilar
productos automáticamente. La siguiente prioridad es mejorar la calidad
de los datos y construir el motor de inteligencia sobre la base de
información histórica y comparativa.

## Estado v4

- v4.0: base multi-tienda desplegada.
- v4.1: collector de Líquidos incorporado.
- Próximo: v4.2, endurecimiento con los primeros logs reales del nuevo sitio.
