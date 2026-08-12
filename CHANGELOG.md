# v5.6.1 — CAV Store Ranking Notifications

- CAV recibe ahora, tras cada revisión HEALTHY, su bloque automático de `🏆 Mejores precios` con el mismo formato usado por las tiendas públicas.
- El ranking CAV usa el precio `MEMBER/cav_member` como `Precio actual`, el precio normal CAV como referencia, y calcula descuento y ahorro informado.
- Se mantiene CAV fuera del comparador público: `comparison_enabled=false` y `personal_comparison_enabled=true`.
- El digest `Tus mejores ventajas CAV` y las alertas de bajas MEMBER permanecen activos como funciones independientes.
- El ranking personal se deduplica por `run_id`: un reintento del mismo run no duplica mensajes, pero cada revisión HEALTHY nueva vuelve a publicar el top 30 en bloques 1-10, 11-20 y 21-30.
- Sin cambios de esquema ni migraciones nuevas; Alembic continúa en `0010_personal_pricing_activation`.

# v5.6.0 — Personal Pricing & CAV Activation

- Activa CAV como fuente personal estable tras tres ciclos de validación de v5.5.2.
- Mantiene CAV fuera del mercado público mediante `comparison_enabled=false`.
- Añade `personal_comparison_enabled` para fuentes elegibles solo en el perfil privado.
- El buscador web alterna entre Mercado público y Con membresía CAV.
- El API `/api/search` acepta `mode=personal`.
- Añade historial contextual por producto, `price_type` y `audience_key`.
- Opportunity Score personal deja el modo preview y usa historia, matching, frescura y escasez reales.
- Añade alertas Telegram por bajas MEMBER y un digest deduplicado de ventajas CAV frente al mercado público.
- Añade `/miprecio <producto>`, `/personal` y `/historialsocio <producto>`.
- Migración Alembic `0010_personal_pricing_activation`.
- Suite total: 165 pruebas.

# v5.5.3 — Search UI Refresh

- Rediseña el buscador web como comparador de precios, sin modificar collectors ni persistencia.
- Mantiene el tema oscuro y mejora jerarquía visual, responsive móvil y accesibilidad.
- La portada muestra tiendas públicas, productos comparables y precios vigentes usando consultas de solo lectura.
- Añade búsquedas rápidas y una explicación breve de comparación, historial y Opportunity Score.
- Las tarjetas de resultado destacan mejor precio público, ahorro frente a la segunda tienda, promedio/mínimo de 90 días y Opportunity Score.
- Ordena visualmente las ofertas por tienda y marca con claridad el ganador.
- CAV diagnóstico sigue excluido de las métricas y del comparador público mediante `comparison_enabled=false`.
- No cambia `/api/search`, matching, scheduler, Telegram ni collectors.
- Sin migraciones nuevas; Alembic continúa en `0009_price_contexts`.
- Suite total: 158 pruebas.

# v5.5.2 — Pagination Boundary & CAV Sharded Catalog Hotfix

- La Vinoteca reconoce la repetición terminal posterior al último rango VTEX como fin de catálogo y no como fallo.
- La Vinoteca acepta `Content-Range`, `REST-Content-Range` y `X-VTEX-Content-Range` como fuentes del total anunciado.
- CAV abandona el índice global que se estanca alrededor del límite de paginación y divide la captura en shards por familia.
- Vinos CAV se subdivide por `wine_type.name` y descubre nuevas facetas cuando el frontend las expone.
- Cada shard CAV termina de forma segura ante una cola sin productos nuevos y mantiene límites plausibles para detectar filtros ignorados.
- CAV permanece en diagnóstico y fuera del comparador público.
- Sin migraciones nuevas; Alembic continúa en `0009_price_contexts`.
- Suite total: 155 pruebas.

# v5.5.1 — La Vinoteca 206 + CAV Rendered Catalog Hotfix

- La Vinoteca acepta HTTP `206 Partial Content` como respuesta válida del catálogo VTEX y usa `Content-Range` para detectar el final.
- Mantiene HTTP `416` como señal segura de fin de rango.
- CAV deja de paginar el HTML SSR estático con `requests`; ahora renderiza el buscador client-side con Playwright.
- CAV extrae preferentemente `.ais-Hits-item` para excluir los bloques editoriales repetidos (ofertas, destacados, liquidación y recomendados).
- Conserva CAV en modo diagnóstico y rechaza cualquier captura parcial o repetida antes de persistirla.
- CAV pasa a `requires_browser=true`; no cambia comparador público ni migraciones.
- Añade regresiones para HTTP 206, `Content-Range` y metadata de CAV.

# v5.4.0 — Catalog Intelligence & Reliability

- Corrige el borde del planificador con tolerancia configurable y estado `DUE_SOON`.
- Muestra última revisión real, próxima revisión exacta y fuente en `/estado`.
- Añade disponibilidad explícita y desactivación tras dos ausencias `HEALTHY`.
- Registra reactivaciones y excluye publicaciones no disponibles del buscador, comparador y favoritos.
- Calcula mínimos, promedios y medianas de 30/90 días, mínimo histórico y frecuencia de descuento.
- Implementa Opportunity Score v1 con pesos 35/30/15/10/10.
- Refuerza matching mediante EAN, SKU y reglas manuales persistentes de equivalencia/exclusión.
- Amplía el comparador y buscador web a 30 resultados.
- Añade `/mas`, `/historial`, `/oportunidades` y `/mejores` al bot.
- Añade reporte semanal de salud y alertas de cercanía al timeout.
- Incorpora la migración Alembic `0008_catalog_intelligence`.
- Suite automatizada ampliada para disponibilidad, historial, score, matching y scheduler.

# v5.3.4 — El Mundo Storefront API Hardening

- Reemplaza `products.json` como fuente principal de El Mundo del Vino por la
  Storefront GraphQL API oficial de Shopify.
- Usa el dominio permanente `elmundodelvino-cl.myshopify.com`, paginación por
  cursor y contexto de precios Chile.
- Añade jitter inicial de 45–90 segundos para separar el request del arranque
  paralelo de los demás collectors.
- Limita la consulta a 75 productos y cinco variantes por página, dentro del
  presupuesto de complejidad tokenless.
- Maneja HTTP 429, GraphQL `THROTTLED`, HTTP 430 y 403 sin fan-out a otras rutas.
- Respeta `Retry-After`; cuando no existe, espera 90 segundos y reintenta una sola vez.
- Conserva un fallback legacy único y de bajo volumen solo para fallos no asociados
  a bloqueo o rate limit.
- Corrige importes GraphQL con decimales como `19990.0`.
- Añade ocho regresiones específicas; suite total: 130 pruebas.
- Sin migraciones nuevas ni variables obligatorias.

# v5.3.3 — Socomep Replacement

- Elimina La Barra del registry activo y de la planificación semanal.
- Integra Socomep mediante catálogo Jumpseller público y paginación convencional.
- Añade extracción de precio actual, precio regular, disponibilidad y secciones de origen.
- Sincroniza `stores.is_active` con el registry en cada ejecución.
- Excluye tiendas deshabilitadas de resultados vigentes del buscador.
- Conserva todos los productos e historiales antiguos sin borrarlos.
- Mantiene El Mundo del Vino cada 12 horas y el límite de 25 minutos por collector.
- Sin migraciones ni variables obligatorias nuevas.

# v5.3.1

- La Barra: fallback por sitemap y fichas JSON-LD; corte rápido cuando el DOM/API no exponen catálogo.
- La Modelo: detección dinámica de 186 páginas y tope de seguridad de 220.

# v5.1.11

- El Mundo del Vino usa un único catálogo global Shopify paginado.
- Se eliminan las solicitudes por colección que disparaban HTTP 429.
- Clasificación local de productos por tipo, etiquetas y nombre.
- Una página posterior limitada conserva el catálogo obtenido como DEGRADED.
- Sin migraciones ni variables nuevas.

# v5.1.10

- Excluye la categoría promocional `mascomprados` / “Adiós Gabriel” del descubrimiento automático de Licor3B.
- Incluye las correcciones de colecciones válidas de El Mundo del Vino de v5.1.9.

# Changelog

## 5.1.9

- Elimina la colección inexistente `/collections/cervezas` de El Mundo del Vino.
- Evita alertas estructurales falsas y solicitudes 404 repetidas.
- Conserva Licores, Whisky, Vinos y Espumantes como colecciones activas.

v5.1.8 — Trusted Partial Catalog Persistence

- El Mundo del Vino persiste capturas parciales plausibles como `DEGRADED`.
- Los HTTP 429 parciales ya no invalidan cientos de productos obtenidos correctamente.
- La comparación histórica no descarta una captura ya clasificada como parcial confiable.

# Changelog

## v5.1.7

- Manejo explícito y conservador de HTTP 429 en El Mundo del Vino.
- Pausas preventivas entre categorías y un único reintento respetando `Retry-After`.
- Conservación de páginas ya recopiladas cuando una página posterior queda limitada.
- Persistencia de catálogos parciales suficientes como `DEGRADED`.
- Resumen multi-tienda enviado inmediatamente después de terminar los collectors.

# v5.1.6 — El Mundo del Vino Resilient Shopify Fallback

- Feed JSON Shopify como fuente preferente.
- HTML como fallback con tres intentos, host alternativo y cache busting.
- Diagnósticos de HTTP 200 sin productos, challenge y tamaño de respuesta.
- Evita fallos intermitentes por variantes de HTML o respuestas de caché.

# Changelog

## 5.1.4
- Corrige la agregación de métricas de collectors HTTP.
- Reconoce URLs Shopify directas y con prefijo de colección.
- Canonicaliza publicaciones de El Mundo del Vino a `/products/<slug>`.
- Añade regresiones automatizadas para ambos fallos.

## v5.1.2 — Tost Browser & GradoÚnico Route Fix

- Cambia Tost a Playwright para esperar el catálogo dinámico real.
- Prioriza el grid principal y excluye el carrusel repetido de 11 recomendaciones.
- Descubre paginación desde el DOM renderizado y mantiene el límite de 25 minutos.
- GradoÚnico abre la primera página sin `?page=1`, evitando respuestas 404 del edge.
- Corrige la ruta oficial de Tequila a `/licores/tequila`.
- El preflight de GradoÚnico valida una categoría real y rechaza respuestas 404.
- Mantiene datos históricos cuando una captura queda incompleta.
- Sin migraciones nuevas ni variables obligatorias.

# Changelog

## v5.1.1 — Tost Grid & Rate-Limit Fix

- Corrige la selección del grid principal de Tost: ya no confunde la colección con el carrusel de 11 recomendaciones.
- Sustituye las descargas paralelas de páginas Tost por paginación secuencial con ritmo adaptativo.
- Respeta `Retry-After` y aplica backoff ante HTTP 429.
- Detecta páginas idénticas consecutivas como posible fallo estructural.
- Conserva el límite global de 25 minutos por tienda.
- GradoÚnico mantiene su preflight y circuit breaker en la misma región.

## v5.1.0 — Stability Hardening & Bounded Collectors

- Reescribe Tost sobre páginas HTML normales y elimina la dependencia operacional de `products.json`.
- Descubre paginación real y procesa hasta tres páginas Tost simultáneamente.
- Fuerza Tost a `BROKEN` cuando la cobertura es menor a 50 productos.
- No persiste capturas parciales con salud `BROKEN`, conservando los datos históricos.
- Añade límite configurable de 25 minutos por collector.
- Mantiene GradoÚnico en la misma región con preflight y circuit breaker.
- Las ejecuciones parciales ya no aparecen como `Crashed` en Railway; solo fallan si ninguna tienda termina correctamente.
- Sin migraciones nuevas.

## v5.0.1 — GradoÚnico Connection Resilience

- Añade preflight de conectividad para los dominios `www` y raíz de GradoÚnico.
- Reduce reintentos y timeout de conexión para evitar esperas repetidas de casi un minuto por categoría.
- Incorpora circuit breaker tras dos fallas TCP consecutivas.
- Si GradoÚnico está inaccesible, conserva sus datos históricos y permite que las otras tiendas continúen.
- No hay migraciones ni variables nuevas.

## v5.0.0 — Four-store Expansion & Unified Run Status

- Añade collectors HTTP para Tost y GradoÚnico.
- Amplía el registry y la ejecución paralela a cuatro tiendas.
- Corrige el matching para grupos con tres o cuatro comercios.
- Muestra hasta cuatro enlaces de compra en Telegram.
- El comparador lista todas las tiendas disponibles por producto.
- Excluye regalos, grabados, personalizados y combos ambiguos del matching automático.
- Envía un resumen compacto con el estado de todos los collectors en cada ejecución.
- Amplía `/estado` con salud, productos y fecha de la última revisión por tienda.
- Mantiene Alembic en `0007_telegram_favorites`; no requiere migración.

## v4.8.0 — Favorites & Personalized Alerts

- Favoritos persistentes por chat autorizado.
- Precio objetivo mediante `/avisar producto bajo precio`.
- Administración con `/misfavoritos` y `/eliminarfavorito`.
- Detección de baja, nueva tienda, cambio de ganador y reposición.
- Mensajes combinados para evitar múltiples avisos del mismo producto.
- Cola `favorite_alerts` con reintentos y estado de entrega.
- Evaluación protegida por cobertura completa y collectors `HEALTHY`.
- Migración `0007_telegram_favorites`.

## v4.7.0 — Interactive Telegram Search Bot

- Bot de Telegram integrado al servicio web de búsqueda existente.
- Búsqueda con `/buscar` y mensajes de texto normales.
- Comandos `/estado` y `/ayuda`.
- Resultados comparativos con botones directos a las tiendas.
- Lista privada de chats autorizados.
- Long polling sin webhook y con reintentos controlados.
- Persistencia del offset de Telegram mediante `0006_telegram_bot_state`.
- Web y bot ejecutándose juntos sin crear un tercer servicio Railway.
- El bot puede deshabilitarse sin afectar el buscador web.

## v4.6.0 — Unified Catalog & Search Engine

- Campos de catálogo para variante, cantidad, alias y texto de búsqueda.
- Migración defensiva `0005_search_catalog`.
- Reindexación automática después de cada ejecución del scraper.
- Motor tolerante a alias, palabras incompletas, errores y volumen.
- Comparación de precios agrupada por producto maestro.
- Filtro de frescura de publicaciones.
- Página web privada protegida por `SEARCH_ACCESS_TOKEN`.
- Endpoint JSON `/api/search` reutilizable por Telegram en v4.7.
- CLI de diagnóstico y servicio Railway independiente.
- Configuración `/railway.search.toml` con healthcheck `/health`.

## v4.5.0 — Cross-store Matching & Price Comparator

- Normalización explicable de marca, variante, volumen y formato.
- Alias conservadores, incluyendo `Etiqueta Negra` ↔ `Black Label`.
- Exclusión automática de packs, cajas, combos y formatos ambiguos.
- Rechazo de volúmenes y variantes incompatibles.
- Matching recíproco para evitar asociaciones uno-a-muchos.
- Confidence score y método de matching guardados en `product_matches`.
- Reagrupación de publicaciones equivalentes bajo `master_products`.
- Comparador real de precios entre Licor3B y Líquidos.
- Ranking por ahorro porcentual y ahorro absoluto, sin techo de precio.
- Alertas cuando cambia la tienda más barata.
- Digest comparativo deduplicado en PostgreSQL.
- Sin migraciones nuevas ni variables obligatorias.

## v4.4.3 — Playwright Wait Fix

- Corrige el uso keyword-only de `arg` en `Page.wait_for_function`.
- Mantiene la recolección paralela y las esperas adaptativas.

## 5.1.3

- Deshabilita Tost y GradoÚnico del registry activo tras fallos repetidos.
- Añade collectors HTTP para El Mundo del Vino y Comercial JP.
- Conserva límite de 25 minutos por tienda, matching, buscador, Telegram y favoritos.
- Sin migraciones nuevas.

## 5.1.5 — Concurrent Master Product Upsert Fix

- Makes `master_products.normalized_key` creation safe across parallel collectors.
- Uses PostgreSQL `ON CONFLICT DO NOTHING` in a short independent transaction.
- Prevents a duplicate master row from invalidating an entire store persistence run.
- Keeps the existing unique constraint as the final source of truth.

## 5.2.0

- Integra La Barra, Donde La Negra y Distribuidora La Modelo.
- Amplía el registry a siete tiendas con cuatro workers máximos.
- La Barra usa Playwright y expansión dinámica controlada.
- Donde La Negra usa categorías WooCommerce públicas y paginación convencional.
- La Modelo usa catálogo público con fallback al catálogo clásico.
- Matching, búsqueda, favoritos, comparador y Telegram operan sobre las siete tiendas.

## v5.3.0

- Donde La Negra: Store API WooCommerce como fuente principal y Playwright como respaldo.
- Donde La Negra: corrección de rutas y control de mayoría de edad.
- La Barra: parser híbrido DOM + JSON/XHR, categorías específicas y detección de mantenimiento.
- La Modelo: techo de paginación ampliado a 180, siempre bajo el presupuesto de 25 minutos.

## v5.3.2 — Store Resilience

- El Mundo del Vino pasa a una frecuencia independiente de 12 horas.
- Reutilización del último snapshot HEALTHY con estado `STALE` cuando corresponde.
- Capturas parciales de El Mundo del Vino no sustituyen datos completos anteriores.
- Corte inmediato si la primera página global responde HTTP 429.
- Pausas de 12–20 segundos entre páginas globales posteriores.
- La Barra queda `PAUSED` y realiza un preflight HTTP semanal de bajo costo.
- Estados `UPDATED`, `STALE`, `PAUSED` y `FAILED` en el resumen global.
- Matching y favoritos pueden usar snapshots vigentes; una tienda pausada no bloquea el resto.

## 5.5.0 — Price Contexts & La Vinoteca
- + La Vinoteca como collector activo basado en catálogo VTEX público.
- + CAV en modo diagnóstico con separación de precio Normal / Oferta / Socio.
- + Modelo genérico de precios contextuales y observaciones históricas.
- + Vista personal `/personal` separada del comparador público.
- + Aislamiento de fuentes diagnósticas en buscador, histórico, favoritos y salida operativa.
- + Migración Alembic `0009_price_contexts`.
