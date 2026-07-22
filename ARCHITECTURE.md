# Arquitectura del Monitor de Ofertas de Licores

**Versión:** 0.1  
**Estado:** Diseño inicial del MVP  
**Plataforma:** Railway + PostgreSQL + Telegram

## 1. Objetivo

Construir una plataforma que monitoree tiendas chilenas de vinos y licores, guarde historial de precios y detecte oportunidades de compra para reventa principalmente en Facebook Marketplace y Mercado Libre.

## 2. Alcance inicial

Tiendas:
- Licor3B
- Líquidos
- La Barra
- Donde La Negra
- Distribuidora La Modelo

Categorías:
- Vinos
- Whisky
- Ron
- Gin
- Vodka
- Tequila
- Espumantes
- Licores
- Packs y cajas

Reglas iniciales:
- Presupuesto por compra: $100.000 CLP
- Máximo por unidad: $30.000 CLP
- Máximo por producto: 3 unidades
- Margen objetivo mínimo: 20%
- Comuna de referencia: La Reina
- Canal de alertas: Telegram

## 3. Principios

1. Cada módulo tendrá una sola responsabilidad.
2. Cada tienda tendrá un conector independiente.
3. Los conectores recolectan datos; no deciden si una compra conviene.
4. Toda observación válida debe guardarse en PostgreSQL.
5. Un error en una tienda no debe detener las demás.
6. Credenciales y límites se configuran mediante variables de entorno.
7. Se preferirá HTTP simple; Playwright se usará solo cuando JavaScript lo haga necesario.

## 4. Flujo general

```text
Railway Cron
    |
    v
Orquestador
    |
    v
Conector de tienda
    |
    v
Descargador HTTP / navegador
    |
    v
Parser
    |
    v
Normalizador y validador
    |
    v
PostgreSQL
    |
    v
Motor de precios
    |
    v
Motor de oportunidades
    |
    v
Telegram
```

## 5. Componentes

### Scheduler
Ejecuta el monitor periódicamente. Frecuencia inicial sugerida:

```cron
0 * * * *
```

### Orquestador
Carga configuración, ejecuta tiendas activas, registra resultados, guarda datos y genera alertas.

### Conectores
Cada tienda tendrá un módulo capaz de descubrir categorías, recorrer paginación, extraer productos y aislar errores.

### Descargadores
- HTTP: `requests` + `BeautifulSoup`.
- Navegador futuro: Playwright.

### Parser
Extrae nombre, marca, categoría, formato, volumen, graduación, precio actual, precio normal, descuento, stock, SKU, EAN, URL e imagen cuando estén disponibles.

### Normalizador
Convierte datos a un formato común, por ejemplo:
- `750 cc` → `750 ml`
- `1 Lt` → `1000 ml`
- precios en texto → enteros CLP

### Validador
Revisa precio, nombre, URL, moneda, duplicados, volumen y coherencia entre precio normal y precio oferta.

### Repositorios
Única capa autorizada para leer y escribir datos en PostgreSQL.

### Motor de comparación
Empareja publicaciones de distintas tiendas usando:
1. EAN.
2. SKU o código del fabricante.
3. Marca + nombre + volumen.
4. Coincidencia difusa.
5. Revisión manual.

### Motor de precios
Calcula precio mínimo, máximo, promedio, mediana, variación y diferencia frente a otras tiendas.

### Motor de oportunidades
Entrega:
- `opportunity_score` de 0 a 100;
- recomendación;
- unidades sugeridas;
- inversión;
- utilidad;
- margen;
- explicación.

### Alertas
Telegram enviará productos nuevos, bajas de precio y oportunidades. No repetirá una alerta sin cambio de precio, stock, margen o puntuación.

## 6. Modelo de datos

### stores
Información y estado de cada tienda.

### categories
Categorías descubiertas por tienda.

### products
Identidad normalizada del producto.

### store_products
Publicación concreta de un producto en una tienda.

### price_observations
Historial de precio y stock.

### scrape_runs
Registro técnico de cada ejecución.

### alerts
Historial y estado de alertas.

### product_matches
Relación entre publicaciones y productos normalizados, con nivel de confianza.

## 7. Estructura objetivo

```text
monitor-ofertas-licores/
├── app/
│   ├── config/
│   ├── connectors/
│   │   ├── base.py
│   │   └── licor3b/
│   ├── downloaders/
│   ├── normalization/
│   ├── validation/
│   ├── database/
│   ├── repositories/
│   ├── engines/
│   ├── notifications/
│   ├── orchestration/
│   └── main.py
├── tests/
├── migrations/
├── scripts/
├── ARCHITECTURE.md
├── README.md
├── Dockerfile
├── requirements.txt
└── .env.example
```

## 8. Estrategia para Licor3B

La versión actual revisa solo la sección de ofertas.

El siguiente conector debe:
1. descubrir categorías;
2. recorrer todas las páginas;
3. extraer el catálogo completo;
4. eliminar duplicados;
5. guardar productos y precios;
6. detectar nuevos productos y cambios;
7. continuar aunque una página falle.

No se incorporará una segunda tienda hasta que Licor3B tenga catálogo completo, historial, registro de ejecuciones y alertas sin duplicados.

## 9. Manejo de errores

Errores recuperables:
- timeout;
- error HTTP temporal;
- producto incompleto;
- página individual defectuosa.

Errores críticos:
- credenciales ausentes;
- base de datos inaccesible;
- configuración inválida;
- estructura completa no reconocida.

Nunca se registrarán tokens, contraseñas ni `DATABASE_URL` en los logs.

## 10. Pruebas

- Unitarias: precios, volúmenes, nombres, descuentos y margen.
- Parser: HTML guardado en `tests/fixtures`.
- Integración: PostgreSQL y alertas duplicadas.
- Humo: configuración, base de datos, lectura de tienda y Telegram.

## 11. Roadmap

### Etapa 1
Estabilizar Licor3B y monitorear catálogo completo.

### Etapa 2
Incorporar Líquidos y comparación entre tiendas.

### Etapa 3
Calcular rentabilidad neta y unidades sugeridas.

### Etapa 4
Añadir La Barra, Donde La Negra y La Modelo.

### Etapa 5
Crear dashboard.

### Etapa 6
Agregar estacionalidad, predicción y optimización del presupuesto.

## 12. Próximo entregable

El próximo cambio de código será el conector de catálogo completo de Licor3B, compatible con esta arquitectura. Todavía no se añadirá una segunda tienda ni inteligencia avanzada.
