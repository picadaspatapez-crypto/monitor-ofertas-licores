# Changelog

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
