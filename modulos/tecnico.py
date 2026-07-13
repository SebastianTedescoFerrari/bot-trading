"""
tecnico.py — Análisis técnico del bot.

Calcula, para un ticker:
  - RSI (14) con contexto de zona (neutral / acercándose / sobreventa-sobrecompra)
  - Medias móviles (EMA20, EMA50, EMA200) y posición del precio
  - Niveles de Fibonacci trazados sobre el máximo/mínimo de los últimos 6 meses
  - Detección de divergencias (candidatas, para confirmar a ojo)

Fuente de datos: yfinance (gratis, sin API key).
Todo el análisis se calcula con datos actuales bajados al momento.
"""

import time

import yfinance as yf
import pandas as pd
import numpy as np


# ── Caché simple en memoria para no golpear a Yahoo de más (rate limit) ──
# Guarda cada descarga por un rato; así consultas repetidas y /revisar pesan mucho menos.
_CACHE = {}


def _cache_get(key, ttl):
    hit = _CACHE.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def _cache_set(key, valor):
    _CACHE[key] = (time.time(), valor)


# Símbolos de cripto conocidos. En yfinance cotizan como "BTC-USD", no "BTC".
# Si el usuario escribe /btc, hay que traducirlo o el bot baja OTRO activo
# (existe una acción "BTC" que cotiza a ~$28 y no tiene nada que ver con Bitcoin).
CRIPTOS = {
    "BTC", "ETH", "SOL", "ADA", "XRP", "DOGE", "BNB", "DOT", "AVAX",
    "MATIC", "POL", "LTC", "LINK", "SHIB", "TRX", "ATOM", "UNI", "ETC",
    "XLM", "BCH", "NEAR", "APT", "ARB", "OP", "FIL", "ICP",
}


def normalizar_ticker(ticker):
    """
    Devuelve (ticker_yfinance, es_cripto).

    - Cripto conocida (BTC, ETH, ...) -> le agrega '-USD' para que yfinance
      baje la cotización real en dólares.
    - Si ya viene con '-USD' (ej: BTC-USD), se respeta y se marca como cripto.
    - Cualquier otro ticker (acciones) se deja igual.
    """
    t = ticker.strip().upper()
    if t.endswith("-USD"):
        return t, True
    if t in CRIPTOS:
        return f"{t}-USD", True
    return t, False


# Horizontes disponibles. "diario" es el default (comportamiento histórico del bot).
TIMEFRAMES = {
    "diario":  {"period": "1y", "interval": "1d",  "fib_barras": 126, "nombre": "Diario (6 meses)", "unidad": "día"},
    "semanal": {"period": "5y", "interval": "1wk",  "fib_barras": 52,  "nombre": "Semanal (1 año)", "unidad": "semana"},
    "1h":      {"period": "1mo", "interval": "60m", "fib_barras": 60,  "nombre": "Intradía 1h (~10 ruedas)", "unidad": "hora"},
}

# Alias que puede escribir el usuario en Telegram -> clave de TIMEFRAMES.
ALIAS_TIMEFRAME = {
    "diario": "diario", "1d": "diario", "d": "diario",
    "semanal": "semanal", "semana": "semanal", "1w": "semanal", "1wk": "semanal", "w": "semanal",
    "1h": "1h", "h": "1h", "hora": "1h", "intradia": "1h", "intradía": "1h",
}


def resolver_timeframe(valor):
    """
    Traduce lo que escribió el usuario (o None) a una config de TIMEFRAMES.
    Devuelve (clave, config) o lanza ValueError si no se reconoce.
    """
    if not valor:
        clave = "diario"
    else:
        clave = ALIAS_TIMEFRAME.get(valor.strip().lower())
        if clave is None:
            opciones = ", ".join(sorted(set(ALIAS_TIMEFRAME.values())))
            raise ValueError(f"Horizonte '{valor}' no reconocido. Usá: {opciones}")
    return clave, TIMEFRAMES[clave]


def bajar_datos(ticker, periodo="1y", intervalo="1d"):
    """
    Baja el histórico de precios según el período/intervalo pedido.

    auto_adjust=False a propósito: yfinance por default ajusta Open/High/Low/Close
    por DIVIDENDOS además de splits, lo que "achica" precios históricos reales
    (ej: YPF mostraba un máximo histórico de hace meses en vez del real de 2005,
    por 20 años de dividendos acumulados). Con auto_adjust=False se mantienen
    los precios tal como se operaron (solo ajustados por splits), que es lo que
    hace falta para niveles técnicos (soportes, resistencias, máximos) reales.

    Además usa caché y reintentos para sobrevivir al rate limit de Yahoo, frecuente
    desde IPs de datacenter (como la de Render).
    """
    key = ("hist", ticker, periodo, intervalo)
    # El histórico completo ("max") cambia poco -> se cachea más tiempo.
    ttl = 3600 if periodo == "max" else 600
    cacheado = _cache_get(key, ttl)
    if cacheado is not None:
        return cacheado

    ultimo_error = None
    for i in range(3):
        try:
            df = yf.Ticker(ticker).history(period=periodo, interval=intervalo, auto_adjust=False)
            if not df.empty:
                _cache_set(key, df)
                return df
            ultimo_error = ValueError(f"No se pudieron bajar datos de {ticker}")
        except Exception as e:
            ultimo_error = e
        if i < 2:
            time.sleep(1.0 * (i + 1))  # espera creciente entre reintentos

    raise ultimo_error if ultimo_error else ValueError(f"No se pudieron bajar datos de {ticker}")


def calcular_rsi(df, periodo=14):
    """RSI clásico de Wilder. Devuelve el valor actual redondeado."""
    delta = df["Close"].diff()
    ganancia = delta.where(delta > 0, 0.0)
    perdida = -delta.where(delta < 0, 0.0)
    # Media exponencial de Wilder (alpha = 1/periodo)
    avg_gan = ganancia.ewm(alpha=1/periodo, adjust=False).mean()
    avg_per = perdida.ewm(alpha=1/periodo, adjust=False).mean()
    rs = avg_gan / avg_per
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 1)


def contexto_rsi(rsi):
    """
    Traduce el número de RSI a una lectura en criollo con zona.
    Umbrales clásicos 30/70, pero avisa cuando se está acercando.
    """
    if rsi < 30:
        estado = "sobreventa"
        texto = f"RSI {round(rsi)} — sobrevendido, suele preceder rebotes (pero puede seguir cayendo)."
    elif rsi < 40:
        estado = "acercandose_sobreventa"
        texto = f"RSI {round(rsi)} — acercándose a sobreventa, atento a un posible piso."
    elif rsi <= 60:
        estado = "neutral"
        texto = f"RSI {round(rsi)} — zona neutral, sin señal de extremo."
    elif rsi <= 70:
        estado = "acercandose_sobrecompra"
        texto = f"RSI {round(rsi)} — acercándose a sobrecompra, el impulso puede estar agotándose."
    else:
        estado = "sobrecompra"
        texto = f"RSI {round(rsi)} — sobrecomprado, puede venir una corrección (pero puede seguir subiendo)."
    return {"valor": rsi, "estado": estado, "texto": texto}


def calcular_medias(df):
    """EMA 20/50/200 y lectura de dónde está el precio respecto a ellas."""
    precio = float(df["Close"].iloc[-1])
    ema20 = float(df["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(df["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
    ema200 = float(df["Close"].ewm(span=200, adjust=False).mean().iloc[-1])

    sobre = [n for n, e in [("EMA20", ema20), ("EMA50", ema50), ("EMA200", ema200)] if precio >= e]
    bajo = [n for n, e in [("EMA20", ema20), ("EMA50", ema50), ("EMA200", ema200)] if precio < e]

    # Lectura simple de tendencia según cuántas medias tiene por encima
    if len(sobre) == 3:
        texto = "Precio por encima de todas las medias — tendencia alcista sana."
    elif len(sobre) == 0:
        texto = "Precio por debajo de todas las medias — tendencia bajista."
    else:
        texto = f"Precio sobre {', '.join(sobre)} y bajo {', '.join(bajo)} — señal mixta."

    return {
        "precio": round(precio, 2),
        "ema20": round(ema20, 2), "ema50": round(ema50, 2), "ema200": round(ema200, 2),
        "texto": texto,
    }


def calcular_fibonacci(df, barras=126):
    """
    Traza los retrocesos de Fibonacci sobre el máximo y mínimo de las últimas N barras
    (velas). El significado de "barras" depende del timeframe (días, semanas u horas).
    Indica entre qué dos niveles está el precio y cuál es el soporte/resistencia más cercano.
    """
    reciente = df.tail(barras)
    maximo = float(reciente["High"].max())
    minimo = float(reciente["Low"].min())
    rango = maximo - minimo
    precio = float(df["Close"].iloc[-1])

    niveles = {
        "0.0 (máx)": maximo,
        "0.236": maximo - 0.236 * rango,
        "0.382": maximo - 0.382 * rango,
        "0.5": maximo - 0.5 * rango,
        "0.618": maximo - 0.618 * rango,
        "0.786": maximo - 0.786 * rango,
        "1.0 (mín)": minimo,
    }

    # Nivel de soporte (el más cercano por debajo) y resistencia (el más cercano por encima)
    soporte = max([v for v in niveles.values() if v <= precio], default=minimo)
    resistencia = min([v for v in niveles.values() if v >= precio], default=maximo)

    def nombre_de(valor):
        return min(niveles.items(), key=lambda kv: abs(kv[1] - valor))[0]

    return {
        "maximo": round(maximo, 2), "minimo": round(minimo, 2),
        "niveles": {k: round(v, 2) for k, v in niveles.items()},
        "soporte": round(soporte, 2), "soporte_nombre": nombre_de(soporte),
        "resistencia": round(resistencia, 2), "resistencia_nombre": nombre_de(resistencia),
        "texto": f"Entre {nombre_de(soporte)} (${round(soporte,2)}) y "
                 f"{nombre_de(resistencia)} (${round(resistencia,2)}).",
    }


def detectar_divergencias(df, periodo_rsi=14, ventana=60, orden=5):
    """
    Detecta divergencias CANDIDATAS entre precio y RSI en las últimas 'ventana' ruedas.
    - Alcista: precio hace mínimo más bajo, RSI hace mínimo más alto.
    - Bajista: precio hace máximo más alto, RSI hace máximo más bajo.

    OJO: la detección automática tiene falsos positivos. El bot la marca como
    CANDIDATA para que la confirmes mirando el gráfico. No es una señal cerrada.
    """
    delta = df["Close"].diff()
    g = delta.where(delta > 0, 0.0).ewm(alpha=1/periodo_rsi, adjust=False).mean()
    p = -delta.where(delta < 0, 0.0).ewm(alpha=1/periodo_rsi, adjust=False).mean()
    rsi_serie = 100 - (100 / (1 + g / p))

    sub = df.tail(ventana).copy()
    rsi_sub = rsi_serie.tail(ventana).reset_index(drop=True)
    precio = sub["Close"].reset_index(drop=True)

    def pivotes_min(serie):
        idx = []
        for i in range(orden, len(serie) - orden):
            if serie[i] == min(serie[i-orden:i+orden+1]):
                idx.append(i)
        return idx

    def pivotes_max(serie):
        idx = []
        for i in range(orden, len(serie) - orden):
            if serie[i] == max(serie[i-orden:i+orden+1]):
                idx.append(i)
        return idx

    resultado = {"alcista": False, "bajista": False, "texto": "Sin divergencias candidatas."}

    min_precio = pivotes_min(precio)
    if len(min_precio) >= 2:
        a, b = min_precio[-2], min_precio[-1]
        if precio[b] < precio[a] and rsi_sub[b] > rsi_sub[a]:
            resultado["alcista"] = True
            resultado["texto"] = ("Posible divergencia ALCISTA (precio marca mínimo más bajo pero "
                                  "el RSI no lo acompaña). CANDIDATA — confirmá en el gráfico.")

    max_precio = pivotes_max(precio)
    if len(max_precio) >= 2:
        a, b = max_precio[-2], max_precio[-1]
        if precio[b] > precio[a] and rsi_sub[b] < rsi_sub[a]:
            resultado["bajista"] = True
            resultado["texto"] = ("Posible divergencia BAJISTA (precio marca máximo más alto pero "
                                  "el RSI no lo acompaña). CANDIDATA — confirmá en el gráfico.")

    return resultado


def calcular_volumen_relativo(df, ventana=20):
    """
    Volumen de la última rueda comparado con su promedio de las últimas 'ventana' ruedas.

    NO es una señal de compra/venta: es un CONFIRMADOR. Un movimiento con volumen alto
    tiene fuerza real detrás; con volumen flojo suele ser un amague. Se usa para darle
    (o quitarle) confianza a la señal técnica, no para generar una nueva.
    """
    vols = df["Volume"].dropna()
    if len(vols) < 5 or float(vols.iloc[-1]) == 0:
        return {"ratio": None, "estado": "sin_datos",
                "texto": "Volumen no disponible para este activo."}

    hoy = float(vols.iloc[-1])
    promedio = float(vols.tail(ventana).mean())
    if promedio <= 0:
        return {"ratio": None, "estado": "sin_datos",
                "texto": "Volumen no disponible para este activo."}

    ratio = hoy / promedio
    if ratio >= 1.5:
        estado = "alto"
        texto = (f"🔊 Volumen {ratio:.1f}x su promedio — hay fuerza real detrás del "
                 f"movimiento, la señal técnica pesa más.")
    elif ratio <= 0.6:
        estado = "bajo"
        texto = (f"🔈 Volumen {ratio:.1f}x su promedio — poco interés hoy, conviene "
                 f"tomar la señal con pinzas (puede ser un amague).")
    else:
        estado = "normal"
        texto = f"🔉 Volumen {ratio:.1f}x su promedio — participación normal."
    return {"ratio": round(ratio, 2), "estado": estado, "texto": texto}


# Cercanía (en %) para considerar que el precio está "pegado" a un nivel de Fibonacci.
UMBRAL_FIB = 0.015  # 1.5%


def semaforo_tecnico(precio, rsi_ctx, medias, fibonacci, divergencias, volumen=None):
    """
    Semáforo técnico MULTIFACTOR y graduado.

    Combina 4 factores que el bot ya calcula, cada uno vota compra (+) / venta (-) /
    neutral (0). El RSI en extremo (sobreventa/sobrecompra) pesa doble porque es la
    señal más fuerte. La suma define el color y la intensidad, y se muestra cuántos
    factores están de acuerdo para que la lectura sea transparente.

    Factores:
      1. RSI          — sobreventa +2 / acercándose +1 / neutral 0 / acercándose -1 / sobrecompra -2
      2. Fibonacci    — pegado a soporte +1 / pegado a resistencia -1 / lejos 0
      3. Medias (EMA) — precio sobre las 3 +1 / bajo las 3 -1 / mixto 0
      4. Divergencia  — alcista +1 / bajista -1 / ninguna 0
    """
    # ── Factor 1: RSI ──
    rsi_signo = {
        "sobreventa": 2, "acercandose_sobreventa": 1, "neutral": 0,
        "acercandose_sobrecompra": -1, "sobrecompra": -2,
    }[rsi_ctx["estado"]]

    # ── Factor 2: cercanía a soporte/resistencia de Fibonacci ──
    sop, res = fibonacci["soporte"], fibonacci["resistencia"]
    dist_sop = (precio - sop) / precio if precio else 1.0
    dist_res = (res - precio) / precio if precio else 1.0
    if dist_sop <= UMBRAL_FIB and dist_sop <= dist_res:
        fib_signo = 1
        fib_txt = f"pegado a soporte Fibonacci {fibonacci['soporte_nombre']} (${sop})"
    elif dist_res <= UMBRAL_FIB:
        fib_signo = -1
        fib_txt = f"pegado a resistencia Fibonacci {fibonacci['resistencia_nombre']} (${res})"
    else:
        fib_signo = 0
        fib_txt = "lejos de soportes/resistencias Fibonacci"

    # ── Factor 3: posición vs medias ──
    n_sobre = sum(precio >= medias[e] for e in ("ema20", "ema50", "ema200"))
    if n_sobre == 3:
        med_signo, med_txt = 1, "sobre las 3 medias (tendencia alcista)"
    elif n_sobre == 0:
        med_signo, med_txt = -1, "bajo las 3 medias (tendencia bajista)"
    else:
        med_signo, med_txt = 0, "posición mixta respecto a las medias"

    # ── Factor 4: divergencias ──
    if divergencias["alcista"]:
        div_signo, div_txt = 1, "divergencia alcista candidata"
    elif divergencias["bajista"]:
        div_signo, div_txt = -1, "divergencia bajista candidata"
    else:
        div_signo, div_txt = 0, "sin divergencias"

    signos = [rsi_signo, fib_signo, med_signo, div_signo]
    net = sum(signos)

    # Cuántos factores (de 4) apuntan en la dirección neta
    if net > 0:
        n_acuerdo = sum(1 for s in signos if s > 0)
    elif net < 0:
        n_acuerdo = sum(1 for s in signos if s < 0)
    else:
        n_acuerdo = 0

    # Tres niveles de intensidad por lado, framado como acción (comprar/vender/esperar).
    if net >= 3:
        color, accion, nivel = "verde", "COMPRAR", "señal fuerte"
    elif net == 2:
        color, accion, nivel = "verde", "COMPRAR", "señal moderada"
    elif net == 1:
        color, accion, nivel = "verde", "Comprar", "señal leve"
    elif net <= -3:
        color, accion, nivel = "rojo", "VENDER", "señal fuerte"
    elif net == -2:
        color, accion, nivel = "rojo", "VENDER", "señal moderada"
    elif net == -1:
        color, accion, nivel = "rojo", "Vender", "señal leve"
    else:
        # net == 0: distinguir "todo plano" de "señales que se cancelan"
        hay_opuestos = any(s > 0 for s in signos) and any(s < 0 for s in signos)
        color, accion = "amarillo", "ESPERAR"
        nivel = "señales mixtas" if hay_opuestos else "sin señal clara"

    titulo = f"{accion} — {nivel}"

    return {
        "color": color,
        "titulo": titulo,
        "accion": accion,
        "nivel": nivel,
        "net": net,
        "n_acuerdo": n_acuerdo,
        "factores": {
            "rsi": {"signo": rsi_signo, "texto": rsi_ctx["texto"]},
            "fibonacci": {"signo": fib_signo, "texto": fib_txt},
            "medias": {"signo": med_signo, "texto": med_txt},
            "divergencia": {"signo": div_signo, "texto": div_txt},
        },
    }


def distancia_maximo_historico(df_diario):
    """
    Compara el precio actual contra el máximo histórico (todo el historial diario),
    a partir de un DataFrame diario ya bajado.
    """
    ath = float(df_diario["High"].max())
    precio = float(df_diario["Close"].iloc[-1])
    desvio = (precio - ath) / ath * 100  # <= 0

    if desvio >= -0.5:
        texto = f"🔝 En máximos históricos (${round(ath, 2)})."
    elif desvio >= -10:
        texto = f"A un {abs(round(desvio, 1))}% de su máximo histórico (${round(ath, 2)})."
    else:
        texto = f"En una caída del {abs(round(desvio, 1))}% desde su máximo histórico (${round(ath, 2)})."

    return {"ath": round(ath, 2), "desvio_pct": round(desvio, 1), "texto": texto}


def calcular_atr(df, periodo=14):
    """
    ATR (Average True Range): cuánto se mueve el activo por vela, en $ y en %.
    Sirve para calibrar stops: ni tan pegados que te barran, ni tan lejos que arriesgues de más.
    """
    high, low, close = df["High"], df["Low"], df["Close"]
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = float(tr.ewm(alpha=1 / periodo, adjust=False).mean().iloc[-1])
    precio = float(close.iloc[-1])
    pct = atr / precio * 100 if precio else 0.0
    return {"atr": round(atr, 2), "pct": round(pct, 1)}


def _rb_direccion(gana, arriesga):
    """
    Clasifica un R:B a partir del % a ganar y del % a arriesgar.
    Devuelve (tipo, ratio). tipo: favorable / neutro / malo / sin_recorrido / pegado.
    """
    if gana < 0.2:
        return "sin_recorrido", None   # el objetivo está pegado (casi no hay para ganar)
    if arriesga < 0.2:
        return "pegado", None          # el stop está pegado (casi no hay para arriesgar)
    ratio = gana / arriesga
    if ratio >= 1.5:
        tipo = "favorable"
    elif ratio >= 1:
        tipo = "neutro"
    else:
        tipo = "malo"
    return tipo, round(ratio, 1)


def calcular_escenarios(precio, fibonacci, net):
    """
    Analiza los DOS escenarios de trade (long y short) usando los niveles de Fibonacci,
    e indica cuál es el más probable según el sesgo del semáforo técnico (net).

    - LONG (comprar): objetivo = resistencia (subís), stop = soporte (bajás).
    - SHORT (vender en corto): objetivo = soporte (baja), stop = resistencia (sube).
    El R:B de uno es el inverso del otro: los niveles favorecen a una sola dirección.
    """
    res, sop = fibonacci["resistencia"], fibonacci["soporte"]
    subida = (res - precio) / precio * 100   # % hasta la resistencia
    bajada = (precio - sop) / precio * 100    # % hasta el soporte

    long_tipo, long_ratio = _rb_direccion(subida, bajada)
    short_tipo, short_ratio = _rb_direccion(bajada, subida)

    if net > 0:
        favorito = "long"
    elif net < 0:
        favorito = "short"
    else:
        favorito = "ninguno"

    return {
        "resistencia": res, "soporte": sop,
        "subida_pct": round(subida, 1), "bajada_pct": round(bajada, 1),
        "long": {"tipo": long_tipo, "ratio": long_ratio},
        "short": {"tipo": short_tipo, "ratio": short_ratio},
        "favorito": favorito,
    }


def calcular_variacion_plazos(df_diario):
    """% de cambio en 1 día, 1 semana (~5 ruedas) y 1 mes (~21 ruedas), sobre datos diarios."""
    close = df_diario["Close"]
    precio = float(close.iloc[-1])

    def cambio(n):
        if len(close) > n:
            ref = float(close.iloc[-1 - n])
            if ref:
                return round((precio - ref) / ref * 100, 1)
        return None

    return {"1d": cambio(1), "1sem": cambio(5), "1mes": cambio(21)}


def detectar_cruce_medias(df, rapida=50, lenta=200, ventana=10):
    """
    Detecta un cruce reciente (últimas 'ventana' velas) de la media rápida sobre la lenta:
      - golden cross (rápida cruza HACIA ARRIBA de la lenta) = sesgo alcista de fondo.
      - death cross  (rápida cruza HACIA ABAJO) = sesgo bajista de fondo.
    Señal lenta, de tendencia mayor. Devuelve None si no hubo cruce reciente.
    """
    if len(df) < lenta + ventana:
        return {"cruce": None, "texto": None}
    ema_r = df["Close"].ewm(span=rapida, adjust=False).mean()
    ema_l = df["Close"].ewm(span=lenta, adjust=False).mean()
    signo = (ema_r - ema_l).apply(lambda x: 1 if x >= 0 else -1)
    reciente = signo.tail(ventana + 1).tolist()

    cruce = None
    for i in range(1, len(reciente)):
        if reciente[i - 1] < 0 and reciente[i] > 0:
            cruce = "golden"
        elif reciente[i - 1] > 0 and reciente[i] < 0:
            cruce = "death"

    if cruce == "golden":
        texto = "⚡ Golden cross reciente (EMA50 sobre EMA200) — sesgo alcista de fondo."
    elif cruce == "death":
        texto = "⚡ Death cross reciente (EMA50 bajo EMA200) — sesgo bajista de fondo."
    else:
        texto = None
    return {"cruce": cruce, "texto": texto}


def detectar_fase(df, ventana=30):
    """
    Detecta la FASE reciente del precio en las últimas 'ventana' velas:
      - "bajando": viene en caída (cuidado con acumular, "cuchillo cayendo").
      - "lateral": se estabilizó / lateraliza (dejó de caer; mejor zona para acumular de a poco).
      - "subiendo": viene recuperando.
    Se mide con el cambio neto punta a punta y el ancho del rango.
    """
    reciente = df["Close"].tail(ventana)
    if len(reciente) < 5:
        return {"fase": "indefinida", "cambio_pct": None}
    ini, fin = float(reciente.iloc[0]), float(reciente.iloc[-1])
    cambio = (fin - ini) / ini * 100 if ini else 0.0

    if cambio <= -8:
        fase = "bajando"
    elif cambio >= 8:
        fase = "subiendo"
    else:
        fase = "lateral"
    return {"fase": fase, "cambio_pct": round(cambio, 1)}


def analisis_tecnico_completo(ticker, timeframe=None):
    """Junta todo el análisis técnico de un ticker en un solo diccionario."""
    ticker_yf, es_cripto = normalizar_ticker(ticker)
    _, cfg = resolver_timeframe(timeframe)
    df = bajar_datos(ticker_yf, periodo=cfg["period"], intervalo=cfg["interval"])
    rsi = calcular_rsi(df)
    precio = round(float(df["Close"].iloc[-1]), 2)
    rsi_ctx = contexto_rsi(rsi)
    medias = calcular_medias(df)
    fibonacci = calcular_fibonacci(df, barras=cfg["fib_barras"])
    divergencias = detectar_divergencias(df)
    volumen = calcular_volumen_relativo(df)
    atr = calcular_atr(df)
    cruce = detectar_cruce_medias(df)

    # El semáforo define el sesgo (net); con eso se decide el escenario más probable.
    semaforo = semaforo_tecnico(precio, rsi_ctx, medias, fibonacci, divergencias, volumen)
    escenarios = calcular_escenarios(precio, fibonacci, semaforo["net"])

    # Datos diarios (todo el historial) una sola vez: sirven para ATH y para momentum.
    df_diario = bajar_datos(ticker_yf, periodo="max", intervalo="1d")

    return {
        "ticker": ticker.strip().upper(),
        "ticker_yf": ticker_yf,
        "es_cripto": es_cripto,
        "precio": precio,
        "timeframe_nombre": cfg["nombre"],
        "timeframe_unidad": cfg["unidad"],
        "rsi": rsi_ctx,
        "medias": medias,
        "fibonacci": fibonacci,
        "divergencias": divergencias,
        "volumen": volumen,
        "atr": atr,
        "escenarios": escenarios,
        "cruce": cruce,
        "fase": detectar_fase(df),
        "ath": distancia_maximo_historico(df_diario),
        "variacion": calcular_variacion_plazos(df_diario),
        "semaforo": semaforo,
    }
