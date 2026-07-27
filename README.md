DATABASE_URL=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Configuración comercial heredada
TOTAL_BUDGET=100000
MAX_UNITS_PER_PRODUCT=3
MIN_TARGET_MARGIN=0.20
DELIVERY_COMMUNE=La Reina

# Alertas inteligentes v4.3
# Una baja se considera relevante si cumple cualquiera de ambos umbrales.
ALERT_MIN_DROP_PERCENT=5
ALERT_MIN_DROP_CLP=1000

# Reenvía el ranking aunque siga idéntico después de este intervalo.
TELEGRAM_DIGEST_INTERVAL_HOURS=24
TELEGRAM_REPORT_LIMIT=30
TELEGRAM_CHANGE_LIMIT=10

# Desactivadas por defecto para reducir ruido.
ALERT_NEW_PRODUCTS=false
ALERT_PRICE_INCREASES=false

# v4.4 Performance Engine (opcionales)
COLLECTOR_WORKERS=2
BLOCK_BROWSER_RESOURCES=true
PRODUCT_WAIT_TIMEOUT_MS=8000
DOM_GROWTH_TIMEOUT_MS=4500
QUICK_SETTLE_MS=250
