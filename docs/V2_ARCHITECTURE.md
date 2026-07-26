# Arquitectura v2.0

## Flujo

```text
Collector -> Pipeline -> Repository -> Analyzer -> Report -> Service
```

## Responsabilidades

- `collectors`: obtienen datos externos y devuelven `CollectedProduct`.
- `pipeline`: coordina cada ejecución sin conocer selectores HTML.
- `repositories`: única capa que lee o escribe datos comerciales.
- `matching`: crea la identidad normalizada del producto.
- `analyzers`: calcula métricas independientes del canal de salida.
- `reports`: convierte resultados en Telegram, CSV o dashboard.
- `services`: integra APIs externas.

Los archivos `app/runner.py`, `app/repository.py` y `app/scrapers/licor3b.py` permanecen como adaptadores temporales de compatibilidad.
