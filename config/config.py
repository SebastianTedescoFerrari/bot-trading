"""
config.py — Configuración del bot.

El TOKEN no vive acá (Git guarda historial). Se resuelve así:
  1. Variable de entorno TELEGRAM_TOKEN  -> se usa en la nube.
  2. Si no está, se lee de config/secreto.py -> para correr LOCAL.
     (config/secreto.py está en .gitignore y no se sube.)

La WATCHLIST no es secreta y queda versionada acá.
"""
import os

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
FMP_API_KEY = os.getenv("FMP_API_KEY", "")

# Fallback local: si no hay variables de entorno, usar config/secreto.py
if not TELEGRAM_TOKEN:
    try:
        from config.secreto import TELEGRAM_TOKEN  # type: ignore
    except Exception:
        pass
if not FMP_API_KEY:
    try:
        from config.secreto import FMP_API_KEY  # type: ignore
    except Exception:
        pass

if not TELEGRAM_TOKEN:
    raise RuntimeError(
        "Falta TELEGRAM_TOKEN. En la nube: seteá la variable de entorno "
        "TELEGRAM_TOKEN. Para correr local: creá config/secreto.py con "
        "TELEGRAM_TOKEN = '...'"
    )

# ─────────────────────────────────────────────────────────────
# WATCHLIST por grupos.
#   /revisar        -> corre TODOS los grupos
#   /revisar us     -> solo un grupo
# Podés analizar cualquier ticker al vuelo con /TICKER aunque no esté acá.
# ─────────────────────────────────────────────────────────────
WATCHLIST_GRUPOS = {'us': ['AAPL',
        'MSFT',
        'NVDA',
        'GOOGL',
        'AMZN',
        'META',
        'TSLA',
        'AVGO',
        'LLY',
        'JPM',
        'V',
        'MA',
        'WMT',
        'XOM',
        'CVX',
        'JNJ',
        'PG',
        'HD',
        'COST',
        'ORCL',
        'NFLX',
        'AMD',
        'KO',
        'PEP',
        'DIS',
        'BAC',
        'MCD',
        'ABBV',
        'CRM',
        'ADBE',
        'WFC',
        'GS',
        'INTC',
        'QCOM',
        'CSCO',
        'PLTR',
        'BRK-B',
        'UNH',
        'CAT',
        'BA',
        'MELI',
        'BABA'],
 'arg': ['YPF',
         'GGAL',
         'PAM',
         'LOMA',
         'BMA',
         'BBAR',
         'SUPV',
         'CRESY',
         'CEPU',
         'TGS',
         'TEO',
         'EDN',
         'IRS',
         'VIST'],
 'cripto': ['BTC',
            'ETH',
            'SOL',
            'XRP',
            'BNB',
            'ADA',
            'DOGE',
            'AVAX',
            'DOT',
            'LINK',
            'LTC',
            'BCH',
            'XLM',
            'ATOM',
            'NEAR']}

# Lista plana con TODOS los activos (la usa /revisar sin grupo).
WATCHLIST = [t for grupo in WATCHLIST_GRUPOS.values() for t in grupo]
