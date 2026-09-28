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

# Clave de Google Gemini (plan gratis) para filtrar y resumir noticias.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
if not GEMINI_API_KEY:
    try:
        from config.secreto import GEMINI_API_KEY  # type: ignore
    except Exception:
        pass

# Chat al que el sistema de alertas manda los mensajes (tu chat con el bot).
# Mismo esquema: variable de entorno en la nube, config/secreto.py en local.
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
if not TELEGRAM_CHAT_ID:
    try:
        from config.secreto import TELEGRAM_CHAT_ID  # type: ignore
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


# ═════════════════════════════════════════════════════════════
# SISTEMA DE ALERTAS (alertas.py) — ver sistema-alertas-diseno.md
# ═════════════════════════════════════════════════════════════
# Cada activo: ticker (como lo ves vos), yf (símbolo en Yahoo), nombre, tipo (define el
# umbral de "movimiento fuerte") y tv (símbolo de TradingView para el link al gráfico).
# Fuera por ahora (Yahoo no los tiene o no son confiables): AL30, CCL, riesgo país,
# Merval en USD. CSI 300 va por el ETF ASHR (el índice en Yahoo viene roto).
ALERTAS_ACTIVOS = [
    # Cripto
    {"ticker": "BTC", "yf": "BTC-USD", "nombre": "Bitcoin", "tipo": "cripto", "tv": "BITSTAMP:BTCUSD"},
    {"ticker": "ETH", "yf": "ETH-USD", "nombre": "Ethereum", "tipo": "cripto", "tv": "BITSTAMP:ETHUSD"},
    # Índices y ETFs de índice
    {"ticker": "SPX", "yf": "^GSPC", "nombre": "S&P 500", "tipo": "indice", "tv": "SP:SPX"},
    {"ticker": "QQQ", "yf": "QQQ", "nombre": "Nasdaq 100 (ETF)", "tipo": "indice", "tv": "NASDAQ:QQQ"},
    {"ticker": "DJI", "yf": "^DJI", "nombre": "Dow Jones", "tipo": "indice", "tv": "DJ:DJI"},
    {"ticker": "MCHI", "yf": "MCHI", "nombre": "China (ETF MSCI)", "tipo": "indice", "tv": "NASDAQ:MCHI"},
    {"ticker": "SX5E", "yf": "^STOXX50E", "nombre": "Euro Stoxx 50", "tipo": "indice", "tv": "TVC:SX5E"},
    {"ticker": "DAX", "yf": "^GDAXI", "nombre": "DAX", "tipo": "indice", "tv": "XETR:DAX"},
    {"ticker": "IBEX", "yf": "^IBEX", "nombre": "IBEX 35", "tipo": "indice", "tv": "BME:IBC"},
    {"ticker": "NI225", "yf": "^N225", "nombre": "Nikkei 225", "tipo": "indice", "tv": "TVC:NI225"},
    {"ticker": "HSI", "yf": "^HSI", "nombre": "Hang Seng", "tipo": "indice", "tv": "TVC:HSI"},
    {"ticker": "CSI300", "yf": "ASHR", "nombre": "CSI 300 (ETF ASHR)", "tipo": "indice", "tv": "AMEX:ASHR"},
    # Tasas, dólar y volatilidad
    {"ticker": "US10Y", "yf": "^TNX", "nombre": "Tasa 10 años EE.UU.", "tipo": "tasa", "tv": "TVC:US10Y"},
    {"ticker": "DXY", "yf": "DX-Y.NYB", "nombre": "Índice dólar", "tipo": "fx", "tv": "TVC:DXY"},
    {"ticker": "EURUSD", "yf": "EURUSD=X", "nombre": "Euro / Dólar", "tipo": "fx", "tv": "FX:EURUSD"},
    {"ticker": "VIX", "yf": "^VIX", "nombre": "Volatilidad S&P 500", "tipo": "volatilidad", "tv": "TVC:VIX"},
    # Materias primas
    {"ticker": "ORO", "yf": "GC=F", "nombre": "Oro", "tipo": "materia_prima", "tv": "TVC:GOLD"},
    {"ticker": "BRENT", "yf": "BZ=F", "nombre": "Petróleo Brent", "tipo": "materia_prima", "tv": "TVC:UKOIL"},
    {"ticker": "COBRE", "yf": "HG=F", "nombre": "Cobre", "tipo": "materia_prima", "tv": "COMEX:HG1!"},
    # Acciones EE.UU.
    {"ticker": "NVDA", "yf": "NVDA", "nombre": "NVIDIA", "tipo": "accion", "tv": "NASDAQ:NVDA"},
    {"ticker": "GOOGL", "yf": "GOOGL", "nombre": "Alphabet", "tipo": "accion", "tv": "NASDAQ:GOOGL"},
    {"ticker": "MSFT", "yf": "MSFT", "nombre": "Microsoft", "tipo": "accion", "tv": "NASDAQ:MSFT"},
    {"ticker": "META", "yf": "META", "nombre": "Meta", "tipo": "accion", "tv": "NASDAQ:META"},
    {"ticker": "AAPL", "yf": "AAPL", "nombre": "Apple", "tipo": "accion", "tv": "NASDAQ:AAPL"},
    {"ticker": "AMZN", "yf": "AMZN", "nombre": "Amazon", "tipo": "accion", "tv": "NASDAQ:AMZN"},
    {"ticker": "TSLA", "yf": "TSLA", "nombre": "Tesla", "tipo": "accion", "tv": "NASDAQ:TSLA"},
    {"ticker": "PLTR", "yf": "PLTR", "nombre": "Palantir", "tipo": "accion", "tv": "NASDAQ:PLTR"},
    {"ticker": "CVX", "yf": "CVX", "nombre": "Chevron", "tipo": "accion", "tv": "NYSE:CVX"},
    {"ticker": "XOM", "yf": "XOM", "nombre": "Exxon Mobil", "tipo": "accion", "tv": "NYSE:XOM"},
    {"ticker": "JPM", "yf": "JPM", "nombre": "JPMorgan", "tipo": "accion", "tv": "NYSE:JPM"},
    {"ticker": "BRK.B", "yf": "BRK-B", "nombre": "Berkshire Hathaway", "tipo": "accion", "tv": "NYSE:BRK.B"},
    {"ticker": "V", "yf": "V", "nombre": "Visa", "tipo": "accion", "tv": "NYSE:V"},
    {"ticker": "BABA", "yf": "BABA", "nombre": "Alibaba", "tipo": "accion", "tv": "NYSE:BABA"},
    # Argentina (ADRs)
    {"ticker": "MELI", "yf": "MELI", "nombre": "MercadoLibre", "tipo": "accion", "tv": "NASDAQ:MELI"},
    {"ticker": "YPF", "yf": "YPF", "nombre": "YPF", "tipo": "accion", "tv": "NYSE:YPF"},
    {"ticker": "GGAL", "yf": "GGAL", "nombre": "Grupo Galicia", "tipo": "accion", "tv": "NASDAQ:GGAL"},
    {"ticker": "BMA", "yf": "BMA", "nombre": "Banco Macro", "tipo": "accion", "tv": "NYSE:BMA"},
    {"ticker": "PAM", "yf": "PAM", "nombre": "Pampa Energía", "tipo": "accion", "tv": "NYSE:PAM"},
    {"ticker": "LOMA", "yf": "LOMA", "nombre": "Loma Negra", "tipo": "accion", "tv": "NYSE:LOMA"},
]

# "Movimiento fuerte": variación diaria (en %) que dispara alerta urgente, por tipo de activo.
UMBRAL_MOVIMIENTO = {
    "accion": 4, "indice": 2, "cripto": 6, "fx": 1,
    "materia_prima": 3, "tasa": 3, "volatilidad": 15,
}
# Niveles de Fibonacci que pueden disparar alerta (las extensiones 1.272/1.618 siempre cuentan).
# 0.236 y 0.786 quedan afuera: el precio los cruza casi a diario y metían mucho ruido.
FIB_NIVELES_ALERTA = ["0.0 (máx)", "0.382", "0.5", "0.618", "1.0 (mín)"]
MOVIMIENTO_INTRADIA = True       # también avisar un movimiento fuerte mientras la vela diaria está en curso
VOLUMEN_MINIMO_CONVICCION = 0.7  # debajo de esto (x promedio), la señal va marcada "baja convicción"
ANTISPAM_HORAS = 24              # la misma señal del mismo activo no se repite antes de esto
HORA_RESUMEN = 8                 # resumen diario de señales no urgentes (hora de Madrid)
HORARIO_ALERTAS = (7, 23)        # el sistema solo corre de 07:00 a 23:00 (hora de Madrid)
ZONA_HORARIA = "Europe/Madrid"


# ═════════════════════════════════════════════════════════════
# MOTOR DE NOTICIAS (modulos/noticias.py + modulos/filtro_ia.py)
# ═════════════════════════════════════════════════════════════
# "log": las filtra y resume pero solo las muestra en el registro (para calibrar).
# "enviar": además las manda a Telegram.
NOTICIAS_MODO = "log"
NOTICIAS_HORAS = 9              # solo noticias de las últimas N horas (cubre la noche, cuando no corre)
NOTICIAS_CADA_MIN = 60          # una pasada de noticias por hora: el plan gratis de Gemini da 20 consultas/día
NOTICIAS_HORAS_TANDA = [8]      # horarios (Madrid) de la tanda de noticias no urgentes; ej: [8, 20]
NOTICIAS_MAX_RESUMEN = 8        # tope de noticias completas por tanda
# Modelos de Gemini en orden de preferencia. Si uno está saturado o ya no existe, se prueba
# el siguiente; si fallan todos, las noticias esperan a la corrida siguiente.
# (Verificado 2026-09-28: los 2.5 ya no atienden claves nuevas; 3.6 Flash respondía mientras
#  3.8/3.7/3.5 estaban saturados, por eso va primero; los Pro no tienen cuota gratis.)
GEMINI_MODELOS = ["gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash",
                  "gemini-flash-latest", "gemini-3.5-flash-lite", "gemini-flash-lite-latest"]

# Fuentes RSS gratuitas. "medio" es el nombre que aparece en el mensaje.
# Reuters, AP, El Cronista e iProfesional no tienen RSS público: van por Google News.
_GN_EN = "https://news.google.com/rss/search?hl=en-US&gl=US&ceid=US:en&q="
_GN_ES = "https://news.google.com/rss/search?hl=es-419&gl=AR&ceid=AR:es-419&q="
NOTICIAS_FUENTES = [
    # Global / EE.UU.
    {"medio": "Reuters", "url": _GN_EN + "site:reuters.com+when:1d"},
    {"medio": "AP", "url": _GN_EN + "site:apnews.com+when:1d"},
    {"medio": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"medio": "CNBC", "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html"},
    {"medio": "CNBC", "url": "https://www.cnbc.com/id/100727362/device/rss/rss.html"},
    {"medio": "MarketWatch", "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
    {"medio": "Reserva Federal", "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
    {"medio": "Politico", "url": "https://rss.politico.com/politics-news.xml"},
    {"medio": "NPR", "url": "https://feeds.npr.org/1004/rss.xml"},
    # Europa / España
    {"medio": "BBC", "url": "https://feeds.bbci.co.uk/news/business/rss.xml"},
    {"medio": "BBC", "url": "https://feeds.bbci.co.uk/news/world/rss.xml"},
    {"medio": "Financial Times", "url": "https://www.ft.com/rss/home"},
    {"medio": "BCE", "url": "https://www.ecb.europa.eu/rss/press.html"},
    {"medio": "El País", "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada"},
    {"medio": "El País", "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/internacional/portada"},
    {"medio": "El País", "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/espana/portada"},
    {"medio": "Expansión", "url": "https://e00-expansion.uecdn.es/rss/portada.xml"},
    {"medio": "Cinco Días", "url": "https://feeds.elpais.com/mrss-s/pages/ep/site/cincodias.elpais.com/portada"},
    {"medio": "DW", "url": "https://rss.dw.com/rdf/rss-en-world"},
    {"medio": "Euronews", "url": "https://www.euronews.com/rss?level=theme&name=news"},
    # Asia / Medio Oriente
    {"medio": "Nikkei Asia", "url": "https://asia.nikkei.com/rss/feed/nar"},
    {"medio": "SCMP", "url": "https://www.scmp.com/rss/4/feed"},
    {"medio": "SCMP", "url": "https://www.scmp.com/rss/92/feed"},
    {"medio": "CNA", "url": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6936"},
    {"medio": "CNA", "url": "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=6511"},
    {"medio": "Al Jazeera", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    # Argentina
    {"medio": "Ámbito", "url": "https://www.ambito.com/rss/pages/economia.xml"},
    {"medio": "Ámbito", "url": "https://www.ambito.com/rss/pages/politica.xml"},
    {"medio": "Infobae", "url": "https://www.infobae.com/arc/outboundfeeds/rss/category/economia/"},
    {"medio": "Infobae", "url": "https://www.infobae.com/arc/outboundfeeds/rss/category/politica/"},
    {"medio": "La Nación", "url": "https://www.lanacion.com.ar/arc/outboundfeeds/rss/category/economia/"},
    {"medio": "La Nación", "url": "https://www.lanacion.com.ar/arc/outboundfeeds/rss/category/politica/"},
    {"medio": "El Cronista", "url": _GN_ES + "site:cronista.com+when:1d"},
    {"medio": "iProfesional", "url": _GN_ES + "site:iprofesional.com+when:1d"},
]
