"""
ejemplo_config.py — Plantilla de configuración.

CÓMO USAR:
  1. Copiá este archivo a config/config.py
  2. Pegá tu token de Telegram (te lo da @BotFather)
  3. Ajustá la watchlist si querés

NUNCA subas config.py con tu token real a ningún lado público (GitHub, etc.).
Por eso config.py está en .gitignore y este ejemplo NO tiene el token real.
"""

# Token del bot de Telegram (lo obtenés hablando con @BotFather en Telegram)
TELEGRAM_TOKEN = "PEGA_ACA_TU_TOKEN"

# ─────────────────────────────────────────────────────────────
# WATCHLIST por grupos.
#   /revisar        -> corre TODOS los grupos
#   /revisar us     -> solo acciones de NY
#   /revisar arg    -> solo ADRs argentinos
#   /revisar cripto -> solo cripto
# Podés analizar cualquier ticker al vuelo con /TICKER aunque no esté acá.
# ─────────────────────────────────────────────────────────────
WATCHLIST_GRUPOS = {
    # Principales acciones que cotizan en Nueva York
    "us": [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "LLY",
        "JPM", "V", "MA", "WMT", "XOM", "CVX", "JNJ", "PG", "HD", "COST", "ORCL",
        "NFLX", "AMD", "KO", "PEP", "DIS", "BAC", "MCD", "ABBV", "CRM", "ADBE",
        "WFC", "GS", "INTC", "QCOM", "CSCO", "PLTR", "BRK-B", "UNH", "CAT", "BA",
        "MELI", "BABA",
    ],
    # ADRs argentinos que cotizan en NY (en dólares)
    "arg": [
        "YPF", "GGAL", "PAM", "LOMA", "BMA", "BBAR", "SUPV", "CRESY", "CEPU",
        "TGS", "TEO", "EDN", "IRS", "VIST",
    ],
    # Principales cripto (el bot les agrega '-USD' solo; a cripto no le corre valuación)
    "cripto": [
        "BTC", "ETH", "SOL", "XRP", "BNB", "ADA", "DOGE", "AVAX", "DOT",
        "LINK", "LTC", "BCH", "XLM", "ATOM", "NEAR",
    ],
}

# Lista plana con TODOS los activos (la usa /revisar sin grupo).
WATCHLIST = [t for grupo in WATCHLIST_GRUPOS.values() for t in grupo]

# OPCIONAL: API key de Financial Modeling Prep para P/E histórico y fundamentales finos.
# Sin esto, el bot funciona igual pero la comparación de P/E vs histórico queda limitada.
# Gratis en https://site.financialmodelingprep.com/ (plan free).
FMP_API_KEY = ""  # dejalo vacío si no la usás todavía
